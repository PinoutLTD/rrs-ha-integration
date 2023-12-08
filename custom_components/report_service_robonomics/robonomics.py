import logging
import time

from homeassistant.core import HomeAssistant
from robonomicsinterface import RWS, Account, Launch, CommonFunctions, Subscriber, SubEvent
from substrateinterface import Keypair, KeypairType
from substrateinterface.exceptions import SubstrateRequestException
from tenacity import Retrying, stop_after_attempt, wait_fixed

from .const import ROBONOMICS_WSS
from .utils import to_thread

_LOGGER = logging.getLogger(__name__)


def create_account() -> (str, Account):
    """Generate Robonomics account and returns seed and Account class"""
    seed = Keypair.generate_mnemonic()
    account = Account(seed, crypto_type=KeypairType.ED25519)
    return seed, account


class Robonomics:
    def __init__(
        self,
        hass: HomeAssistant,
        controller_seed: str,
        owner_address: str,
        owner_seed: str = None,
    ):
        self.hass: HomeAssistant = hass
        self.controller_seed: str = controller_seed
        self.controller_account: Account = Account(
            self.controller_seed, crypto_type=KeypairType.ED25519
        )
        self.controller_address: str = self.controller_account.get_address()
        self.owner_address: str = owner_address
        self.owner_seed = owner_seed
        self.current_wss: str = ROBONOMICS_WSS[0]
        self.balance_is_ok = False

    async def async_init(self) -> None:
        if not await self._check_rws():
            await self._buy_rws()
        if not await self._check_rws_devices():
            await self._add_controller_to_devices()

    @to_thread
    def _buy_rws(self):
        self._check_owner_balance()
        while not self.balance_is_ok:
            time.sleep(2)
        _LOGGER.debug(f"Start buying RWS to {self.owner_address}")
        if self.owner_seed is not None:
            account = Account(
                self.owner_seed,
                crypto_type=KeypairType.ED25519,
                remote_ws=self.current_wss,
            )
            rws = RWS(account)
            auction = rws.get_auction_queue()[0]
            res = rws.bid(auction, 10**9 + 1)
            _LOGGER.debug(f"RWS was bought with result {res}")

    def _check_owner_balance(self) -> bool:
        if self.owner_seed is not None:
            account = Account(
                self.owner_seed,
                crypto_type=KeypairType.ED25519,
                remote_ws=self.current_wss,
            )
            common_functions = CommonFunctions(account)
            account_info = common_functions.get_account_info()
            balance = account_info['data']['free']/1000000000
            _LOGGER.debug(f"Owner balance is {balance}")
            if balance > 1:
                self.balance_is_ok = True
            else:
                self.balance_is_ok = False
                self.subscriber = Subscriber(account, SubEvent.Transfer, self._callback_event)
            
        _LOGGER.error("Owner seed is None. Can't buy subscription.")

    def _callback_event(self, data):
        if data['to'] == self.owner_address:
            _LOGGER.debug(f"Got {data['amount']} XRT")
            self.balance_is_ok = True
            self.subscriber.cancel()

    @to_thread
    def _add_controller_to_devices(self) -> None:
        _LOGGER.debug(f"Start add controller {self.controller_address} to RWS devices to owner {self.owner_address}")
        if self.owner_seed is not None:
            account = Account(
                self.owner_seed,
                crypto_type=KeypairType.ED25519,
                remote_ws=self.current_wss,
            )
            rws = RWS(account)
            res = rws.set_devices([self.controller_address])
            _LOGGER.debug(
                f"Controller was added with result {res}"
            )
        else:
            _LOGGER.error("Owner seed is None. Can't add controller to devices.")

    @to_thread
    def _check_rws_devices(self) -> bool:
        rws = RWS(self.controller_account)
        devices = rws.get_devices(self.owner_address)
        _LOGGER.debug(f"RWS devices: {devices}")
        return self.controller_address in devices

    @to_thread
    def _check_rws(self) -> bool:
        rws = RWS(self.controller_account)
        return rws.get_ledger(self.owner_address) is not None
        # while rws.get_ledger(self.owner_address) is None:
        #     time.sleep(1)
        # _LOGGER.debug(f"Account {self.owner_address} has RWS")

    def _change_current_wss(self) -> None:
        """Set next current wss"""

        current_index = ROBONOMICS_WSS.index(self.current_wss)
        if current_index == (len(ROBONOMICS_WSS) - 1):
            next_index = 0
        else:
            next_index = current_index + 1
        self.current_wss = ROBONOMICS_WSS[next_index]
        _LOGGER.debug(f"New Robonomics ws is {self.current_wss}")
        self.controller_account: Account = Account(
            seed=self.controller_seed,
            crypto_type=KeypairType.ED25519,
            remote_ws=self.current_wss,
        )

    @to_thread
    def send_launch(self, address: str, ipfs_hash: str) -> None:
        for attempt in Retrying(
            wait=wait_fixed(2), stop=stop_after_attempt(len(ROBONOMICS_WSS))
        ):
            with attempt:
                try:
                    _LOGGER.debug(f"Start creating launch with ipfs hash: {ipfs_hash}")
                    launch = Launch(
                        self.controller_account, rws_sub_owner=self.owner_address
                    )
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
