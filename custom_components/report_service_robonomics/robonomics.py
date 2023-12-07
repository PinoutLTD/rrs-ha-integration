import logging
import time

from homeassistant.core import HomeAssistant
from robonomicsinterface import RWS, Account, Launch
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

    async def async_init(self) -> None:
        await self._check_rws()
        if not await self._check_rws_devices():
            await self._add_controller_to_devices()

    @to_thread
    def _add_controller_to_devices(self) -> None:
        if self.owner_seed is not None:
            account = Account(
                self.owner_seed,
                crypto_type=KeypairType.ED25519,
                remote_ws=self.current_wss,
            )
            rws = RWS(account)
            rws.set_devices([self.controller_address])
            _LOGGER.debug(
                f"Controller {self.controller_address} was added to RWS devices to owner {self.owner_address}"
            )
        else:
            _LOGGER.error("Owner seed is None. Can't add controller to devices.")

    @to_thread
    def _check_rws_devices(self) -> bool:
        rws = RWS(self.controller_account)
        return self.controller_address in rws.get_devices(self.owner_address)

    @to_thread
    def _check_rws(self) -> None:
        rws = RWS(self.controller_account)
        while rws.get_ledger(self.owner_address) is None:
            time.sleep(1)
        _LOGGER.debug(f"Account {self.owner_address} has RWS")

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
