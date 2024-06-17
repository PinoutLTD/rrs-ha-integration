import logging
import time

from homeassistant.core import HomeAssistant
from robonomicsinterface import (
    RWS,
    Account,
    Launch,
    CommonFunctions,
    Subscriber,
    SubEvent,
)
from substrateinterface import Keypair, KeypairType
from substrateinterface.exceptions import SubstrateRequestException
from tenacity import Retrying, stop_after_attempt, wait_fixed
import typing as tp

from .const import ROBONOMICS_WSS, DOMAIN, SERVICE_STATUS
from .utils import to_thread, ReportServiceStatus, set_service_status

_LOGGER = logging.getLogger(__name__)


def create_account() -> (str, Account):
    """Generate Robonomics account and returns seed and Account class"""
    seed = Keypair.generate_mnemonic()
    account = Account(seed, crypto_type=KeypairType.ED25519)
    return seed, account


def get_address_for_seed(seed: str) -> str:
    acc = Account(seed, crypto_type=KeypairType.ED25519)
    return acc.get_address()


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
        if not await self.get_rws_left_days():
            await self._buy_rws()
        if not await self._check_rws_devices():
            await self._add_controller_to_devices()
        set_service_status(self.hass, ReportServiceStatus.Work)

    @to_thread
    def get_rws_left_days(self) -> tp.Optional[int]:
        rws = RWS(Account(remote_ws=self.current_wss))
        left_days = rws.get_days_left(addr=self.owner_address)
        _LOGGER.debug(
            f"Subscription is active: {bool(left_days)}, left days: {left_days}"
        )
        if not left_days:
            set_service_status(self.hass, ReportServiceStatus.WaitPinataCreds)
        else:
            set_service_status(self.hass, ReportServiceStatus.Work)
        return left_days

    @to_thread
    def _buy_rws(self):
        self._check_owner_balance()
        while not self.balance_is_ok:
            set_service_status(self.hass, ReportServiceStatus.WaitTokens)
            time.sleep(2)
            self._check_owner_balance()
        set_service_status(self.hass, ReportServiceStatus.BuyingRWS)
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

    def _get_owner_balance(self) -> float:
        if self.owner_seed is not None:
            account = Account(
                self.owner_seed,
                crypto_type=KeypairType.ED25519,
                remote_ws=self.current_wss,
            )
            common_functions = CommonFunctions(account)
            account_info = common_functions.get_account_info()
            balance = account_info["data"]["free"] / 1000000000
            _LOGGER.debug(f"Owner balance is {balance}")
            return balance
        else:
            _LOGGER.error("Owner seed is None. Can't buy subscription.")

    def _check_owner_balance(self) -> bool:
        balance = self._get_owner_balance()
        if balance > 1:
            self.balance_is_ok = True
        else:
            self.balance_is_ok = False
            self.subscriber = Subscriber(
                Account(), SubEvent.Transfer, self._callback_event
            )

    def _callback_event(self, data):
        if data["to"] == self.owner_address:
            _LOGGER.debug(f"Got {data['amount']} XRT")
            if self._get_owner_balance() > 1:
                self.balance_is_ok = True
                self.subscriber.cancel()
            else:
                _LOGGER.debug("Balance is not enough, wait for more xrt")

    @to_thread
    def _add_controller_to_devices(self) -> None:
        _LOGGER.debug(
            f"Start add controller {self.controller_address} to RWS devices to owner {self.owner_address}"
        )
        if self.owner_seed is not None:
            account = Account(
                self.owner_seed,
                crypto_type=KeypairType.ED25519,
                remote_ws=self.current_wss,
            )
            rws = RWS(account)
            res = rws.set_devices([self.controller_address])
            _LOGGER.debug(f"Controller was added with result {res}")
        else:
            _LOGGER.error("Owner seed is None. Can't add controller to devices.")

    @to_thread
    def _check_rws_devices(self) -> bool:
        rws = RWS(self.controller_account)
        devices = rws.get_devices(self.owner_address)
        res = self.controller_address in devices
        _LOGGER.debug(f"RWS devices: {devices}, controller in devices: {res}")
        return res

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
