"""The site's link to the Robonomics chain: one client, one publishing queue.

The client comes from robonomics-interface. It connects on first use, keeps
one connection with the parsed runtime metadata, checks that the node belongs
to the configured network, and reconnects on its own. What happens to a record
that cannot be published right now is `publisher.DatalogPublisher`'s business.
"""

import json
import logging
from collections.abc import Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util.ssl import client_context
from robonomicsinterface import Keypair, RobonomicsClient, generate_mnemonic

from .const import DATALOG_QUEUE_STORAGE_KEY, NETWORK_GENESIS, NETWORK_WSS
from .ipfs import IPFS
from .publisher import DatalogPublisher, Pending
from .utils.ha_storage import async_load_from_store, async_save_to_store

_LOGGER = logging.getLogger(__name__)


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

        self.sender_keypair: Keypair = Keypair.from_secret(sender_seed)
        self.sender_address: str = self.sender_keypair.address

        self.client = RobonomicsClient(
            NETWORK_WSS[network],
            genesis_hash=NETWORK_GENESIS[network],
            # Home Assistant's own TLS context, built when HA starts. Without
            # it the WebSocket library builds a fresh one on every connection,
            # reading the CA bundle from disk inside the event loop, which HA
            # reports as "Detected blocking call".
            ssl=client_context(),
        )
        self.publisher = DatalogPublisher(
            self.client.datalog,
            self.sender_keypair,
            # Without an owner the site publishes on its own subscription.
            owner_address or self.sender_address,
            save=self._save_queue,
            on_dropped=self._on_dropped,
            schedule=self._schedule,
            start_task=lambda coro: hass.async_create_background_task(
                coro, "robonomics_report_service datalog"
            ),
        )

    @staticmethod
    def generate_seed() -> str:
        """Return mnemonic phrase as seed for account"""
        return generate_mnemonic()

    async def async_start(self) -> None:
        """Pick up the reports that were waiting when Home Assistant stopped."""

        saved = await async_load_from_store(self.hass, DATALOG_QUEUE_STORAGE_KEY)
        self.publisher.restore(saved.get("pending", []))
        self.publisher.kick()

    async def async_close(self) -> None:
        await self.publisher.close()
        await self.client.close()

    async def send_datalog(self, data_to_send: str | dict, report: bool = True) -> None:
        """Queue a record for the datalog; it is published in the background.

        `report` says the payload is a CID of files on Pinata: such a record is
        retried when the network fails and unpinned when the chain refuses it.
        A heartbeat is not a report.
        """

        if isinstance(data_to_send, dict):
            data_to_send = json.dumps(data_to_send, separators=(",", ":"))
        await self.publisher.publish(data_to_send, report)

    def _schedule(self, delay: float, action: Callable[[], None]) -> Callable[[], None]:
        # Marked as a callback so Home Assistant runs it in the event loop,
        # not in its executor.
        return async_call_later(self.hass, delay, callback(lambda _now: action()))

    async def _save_queue(self, pending: list[dict]) -> None:
        await async_save_to_store(
            self.hass, DATALOG_QUEUE_STORAGE_KEY, {"pending": pending}
        )

    async def _on_dropped(self, item: Pending, reason: str) -> None:
        if not item.report:
            return
        result = await self.ipfs.unpin_files_from_pinata(item.payload)
        if result and result.failed:
            _LOGGER.warning(
                "Pinata cleanup incomplete after a dropped report "
                "(removed=%s/%s, failed=%s)",
                result.succeeded,
                result.attempted,
                result.failed,
            )
