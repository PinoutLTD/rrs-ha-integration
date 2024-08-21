import asyncio
import logging
import time
import typing as tp

from homeassistant.core import HomeAssistant
from robonomicsinterface import (
    RWS,
    Account,
    Datalog,
    Subscriber,
    SubEvent,
)
from substrateinterface import Keypair, KeypairType
from substrateinterface.exceptions import SubstrateRequestException
from tenacity import Retrying, stop_after_attempt, wait_fixed
from collections import deque

from .const import ROBONOMICS_WSS, OWNER_ADDRESS
from .ipfs import IPFS

_LOGGER = logging.getLogger(__name__)


class Robonomics:
    def __init__(
        self,
        hass: HomeAssistant,
        sender_seed: str,
    ):
        self.hass: HomeAssistant = hass
        self.sender_seed: str = sender_seed
        self.sender_account: Account = Account(
            self.sender_seed, crypto_type=KeypairType.ED25519
        )
        self.sender_address: str = self.sender_account.get_address()
        _LOGGER.debug(f"Sender address: {self.sender_address}")
        self.current_wss: str = ROBONOMICS_WSS[0]
        self.subscriber = None
        self._datalog_queue = deque()
        self._datalogs_are_sending = False

    @staticmethod
    def generate_seed() -> str:
        seed = Keypair.generate_mnemonic()
        return seed

    async def wait_for_rws(self) -> None:
        sender_in_rws = await self.hass.async_add_executor_job(
            self._check_sender_in_rws
        )
        if not sender_in_rws:
            self.subscriber = Subscriber(
                Account(), SubEvent.NewDevices, self._callback_event
            )
            while self.subscriber is not None:
                await asyncio.sleep(1)
    
    async def send_datalog(self, data_to_send: str) -> None:
        await self._handle_datalog_request(data_to_send)

    def _retry_decorator(func: tp.Callable):
        def wrapper(self, *args, **kwargs):
            for attempt in Retrying(
                wait=wait_fixed(2), stop=stop_after_attempt(len(ROBONOMICS_WSS))
            ):
                with attempt:
                    try:
                        res = func(self, *args, **kwargs)
                        return res
                    except TimeoutError:
                        self._change_current_wss()
                        raise TimeoutError
                    except SubstrateRequestException as e:
                        if e.args[0]["code"] == 1014:
                            _LOGGER.warning(f"Datalog sending exception: {e}, retrying...")
                            time.sleep(8)
                            raise e
                        else:
                            _LOGGER.warning(f"Datalog sending exception: {e}")
                            return False
                    except Exception as e:
                        _LOGGER.warning(f"Datalog sending exeption: {e}")
                        return False
                    
        return wrapper

    async def _handle_datalog_request(self, data_to_send: str) -> None:
        self._datalog_queue.append(data_to_send)
        _LOGGER.debug(f"New datalog request, queue length: {len(self._datalog_queue)}")
        if not self._datalogs_are_sending:
            await self._async_send_datalog_from_queue()

    async def _async_send_datalog_from_queue(self) -> None:
        self._datalogs_are_sending = True
        data_to_send = self._datalog_queue.popleft()
        res = await self.hass.async_add_executor_job(self._send_datalog, data_to_send)
        if not res:
            await IPFS(self.hass).unpin_from_pinata(data_to_send)
        if len(self._datalog_queue) > 0:
            asyncio.ensure_future(self._async_send_datalog_from_queue())
        else:
            self._datalogs_are_sending = False

    @_retry_decorator
    def _send_datalog(self, data_to_send: str) -> bool:
        _LOGGER.debug(f"Start creating datalog with data: {data_to_send}")
        datalog = Datalog(
            self.sender_account, rws_sub_owner=OWNER_ADDRESS
        )
        receipt = datalog.record(data_to_send)
        _LOGGER.debug(f"Datalog created with hash: {receipt}, {len(self._datalog_queue)} datalogs left in the queue")
        return True

    def _check_sender_in_rws(self) -> bool:
        rws = RWS(self.sender_account)
        devices = rws.get_devices(OWNER_ADDRESS)
        res = self.sender_address in devices
        _LOGGER.debug(f"RWS devices: {devices}, controller in devices: {res}")
        return res

    def _callback_event(self, data):
        if data[0] == OWNER_ADDRESS:
            if self.sender_address in data[1]:
                self.subscriber.cancel()
                self.subscriber = None

    def _change_current_wss(self) -> None:
        """Set next current wss"""

        current_index = ROBONOMICS_WSS.index(self.current_wss)
        if current_index == (len(ROBONOMICS_WSS) - 1):
            next_index = 0
        else:
            next_index = current_index + 1
        self.current_wss = ROBONOMICS_WSS[next_index]
        _LOGGER.debug(f"New Robonomics ws is {self.current_wss}")
        self.sender_account: Account = Account(
            seed=self.sender_seed,
            crypto_type=KeypairType.ED25519,
            remote_ws=self.current_wss,
        )
