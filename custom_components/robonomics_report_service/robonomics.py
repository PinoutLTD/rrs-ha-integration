import asyncio
import json
import logging
from collections import deque

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .chain import Keypair
from .chain.client import (
    ChainError,
    ExtrinsicFailedError,
    RobonomicsClient,
    RpcError,
)
from .const import NETWORK_WSS
from .exceptions import RobonomicsError
from .ipfs import IPFS

_LOGGER = logging.getLogger(__name__)

# Only transport trouble is worth another endpoint; a call the chain itself
# rejected will be rejected again.
RETRYABLE_ERRORS = (RpcError, ChainError, TimeoutError, OSError)


class Robonomics:
    """Main class to handle Robonomics functionality"""

    def __init__(
        self,
        hass: HomeAssistant,
        network: str,
        ipfs: IPFS,
        sender_seed: str,
        owner_address: str | None = None,
    ):
        self.hass: HomeAssistant = hass
        self.ipfs: IPFS = ipfs
        self.sender_seed: str = sender_seed
        self.wss_endpoints: list[str] = NETWORK_WSS[network]
        self.current_wss: str = self.wss_endpoints[0]

        self.sender_keypair: Keypair = Keypair.create_from_secret(sender_seed)
        self.sender_address: str = self.sender_keypair.ss58_address

        self._owner_address = owner_address
        self._clients: dict[str, RobonomicsClient] = {}

        self._datalog_queue = deque()
        self._worker_task: asyncio.Task | None = None
        self._queue_lock = asyncio.Lock()

    @staticmethod
    def generate_seed() -> str:
        """Return mnemonic phrase as seed for account"""
        return Keypair.generate_mnemonic()

    async def send_datalog(self, data_to_send: str | dict) -> None:
        """Send datalog, async style"""
        if isinstance(data_to_send, dict):
            data_to_send = json.dumps(data_to_send)
        await self._handle_datalog_request(data_to_send)

    def _client(self) -> RobonomicsClient:
        """One client per endpoint, so parsed metadata is reused."""

        if self.current_wss not in self._clients:
            self._clients[self.current_wss] = RobonomicsClient(
                async_get_clientsession(self.hass), self.current_wss
            )
        return self._clients[self.current_wss]

    async def _handle_datalog_request(self, data_to_send: str) -> None:
        self._datalog_queue.append(data_to_send)
        async with self._queue_lock:
            if self._worker_task is None or self._worker_task.done():
                self._worker_task = self.hass.async_create_task(
                    self._datalog_worker()
                )

    async def _datalog_worker(self) -> None:
        try:
            while self._datalog_queue:
                data_to_send = self._datalog_queue.popleft()

                try:
                    await self._send_datalog(data_to_send)
                except RobonomicsError as e:
                    _LOGGER.warning(
                        "Datalog send failed "
                        "(will drop payload from queue): %s",
                        e,
                    )
                    try:
                        result = await self.ipfs.unpin_files_from_pinata(
                            data_to_send
                        )
                    except Exception:
                        result = None

                    if result and result.failed:
                        _LOGGER.warning(
                            "Pinata cleanup incomplete after datalog "
                            "failure (removed=%s/%s, failed=%s)",
                            result.succeeded,
                            result.attempted,
                            result.failed,
                        )

        finally:
            # In case the worker reached the end of the queue,
            # but did not have time to set worker_task = None,
            # and at the same time a new request for the datalog appeared.
            async with self._queue_lock:
                self._worker_task = None
                if self._datalog_queue:
                    self._worker_task = self.hass.async_create_task(
                        self._datalog_worker()
                    )

    async def _send_datalog(self, data_to_send: str) -> str:
        """Publish one record, trying each endpoint before giving up."""

        last_error: Exception | None = None

        for _ in range(len(self.wss_endpoints)):
            try:
                block_hash = await self._client().record_datalog(
                    self.sender_keypair,
                    data_to_send,
                    # Without an owner the site publishes on its own subscription.
                    self._owner_address or self.sender_address,
                )
            except ExtrinsicFailedError as e:
                # The chain accepted the extrinsic and refused the call: a
                # missing or expired subscription looks exactly like this.
                raise RobonomicsError(f"Failed to send datalog ({e})") from e
            except RETRYABLE_ERRORS as e:
                _LOGGER.debug("Datalog attempt on %s failed: %s", self.current_wss, e)
                last_error = e
                self.change_current_wss()
                continue

            _LOGGER.debug("Datalog is recorded in block %s", block_hash)
            return block_hash

        raise RobonomicsError(
            f"Failed to send datalog ({self._exc_short(last_error)})"
        ) from last_error

    def change_current_wss(self) -> None:
        """Set next current wss"""

        current_index = self.wss_endpoints.index(self.current_wss)
        next_index = (current_index + 1) % len(self.wss_endpoints)
        self.current_wss = self.wss_endpoints[next_index]
        _LOGGER.debug("New Robonomics ws is %s", self.current_wss)

    @staticmethod
    def _exc_short(e: BaseException | None) -> str:
        if e is None:
            return "no endpoint answered"
        name = e.__class__.__name__
        msg = str(e).strip()
        return f"{name}: {msg}" if msg else name
