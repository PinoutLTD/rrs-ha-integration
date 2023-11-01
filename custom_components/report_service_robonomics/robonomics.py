import asyncio
import logging
import time

from homeassistant.core import HomeAssistant
from robonomicsinterface import RWS, Account, Launch, SubEvent, Subscriber
from substrateinterface import Keypair, KeypairType
from substrateinterface.exceptions import SubstrateRequestException
from tenacity import Retrying, stop_after_attempt, wait_fixed

from .const import ACCOUNT_SEED, ROBONOMICS_WSS
from .utils import async_load_from_store, async_save_to_store, to_thread

_LOGGER = logging.getLogger(__name__)


class Robonomics:
    def __init__(self, hass: HomeAssistant):
        self.hass: HomeAssistant = hass
        self.owner_seed: str | None = None
        self.owner_account: Account | None = None
        self.owner_address: str | None = None
        self.current_wss: str = ROBONOMICS_WSS[0]
        self.rws_is_ok: bool = False

    async def async_init(self) -> None:
        await self._get_or_generate_account()
        self.rws_is_ok = await self._check_rws()
        if self.rws_is_ok:
            _LOGGER.debug("RWS is ok")
            return
        _LOGGER.debug("Wait for rws setup...")
        while not self.rws_is_ok:
            await asyncio.sleep(2)
        _LOGGER.debug("RWS is ok")

    async def _get_or_generate_account(self) -> None:
        storage_data = await async_load_from_store(self.hass, ACCOUNT_SEED)
        self.owner_seed = storage_data["seed"]
        if self.owner_seed == {}:
            self.owner_seed = Keypair.generate_mnemonic()
            await async_save_to_store(self.hass, ACCOUNT_SEED, {"seed": self.owner_seed})
            _LOGGER.debug("Saved new owner seed")
        self.owner_account = Account(self.owner_seed, crypto_type=KeypairType.ED25519)
        self.owner_address = self.owner_account.get_address()
        _LOGGER.debug(f"Owner address: {self.owner_address}")

    @to_thread
    def _check_rws(self) -> None:
        account = Account(remote_ws=self.current_wss)
        rws = RWS(account)
        if rws.get_ledger(self.owner_address) is not None:
            if self.owner_address in rws.get_devices(self.owner_address):
                return True
            else:
                _LOGGER.debug(f"Address {self.owner_address} is not in rws devices")
        else:
            _LOGGER.debug(f"Account {self.owner_address} has no RWS")
        self.subscriber = Subscriber(
            account,
            SubEvent.NewDevices,
            subscription_handler=self._callback_new_event,
        )
        return False

    def _callback_new_event(self, data) -> None:
        if data[0] == self.owner_address:
            if self.owner_address in data[1]:
                _LOGGER.debug(f"Owner address was added to rws devices")
                self.subscriber.cancel()
                self.rws_is_ok = True

    def _change_current_wss(self) -> None:
        """Set next current wss"""

        current_index = ROBONOMICS_WSS.index(self.current_wss)
        if current_index == (len(ROBONOMICS_WSS) - 1):
            next_index = 0
        else:
            next_index = current_index + 1
        self.current_wss = ROBONOMICS_WSS[next_index]
        _LOGGER.debug(f"New Robonomics ws is {self.current_wss}")
        self.owner_account: Account = Account(
            seed=self.owner_seed, crypto_type=KeypairType.ED25519, remote_ws=self.current_wss
        )

    @to_thread
    def send_launch(self, address: str, ipfs_hash: str) -> None:
        for attempt in Retrying(wait=wait_fixed(2), stop=stop_after_attempt(len(ROBONOMICS_WSS))):
            with attempt:
                try:
                    _LOGGER.debug(f"Start creating launch with ipfs hash: {ipfs_hash}")
                    launch = Launch(self.owner_account, rws_sub_owner=self.owner_address)
                    receipt = launch.launch(address, ipfs_hash)
                except TimeoutError:
                    self._change_current_wss()
                    raise TimeoutError
                except SubstrateRequestException as e:
                    if e.args[0]["code"] == 1014:
                        _LOGGER.warning(f"Launch sending exception: {e}, retrying...")
                        time.sleep(8)
                        raise e
                    else:
                        _LOGGER.warning(f"Launch sending exception: {e}")
                        return None
                except Exception as e:
                    _LOGGER.warning(f"Launch sending exeption: {e}")
                    return None
        _LOGGER.debug(f"Launch created with hash: {receipt}")
