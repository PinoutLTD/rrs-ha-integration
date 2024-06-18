import logging
import typing as tp

from homeassistant.core import HomeAssistant
from pinatapy import PinataPy

from .utils import async_load_from_store
from .const import STORAGE_PINATA_CREDS, CONF_PINATA_PUBLIC, CONF_PINATA_SECRET

_LOGGER = logging.getLogger(__name__)


async def pin_to_pinata(
    hass: HomeAssistant, dirname: str, pinata_public: str, pinata_secret: str
) -> tp.Optional[str]:
    """Add file to Pinata service

    :param hass:  Home Assistant instance
    :param dirname: path to the directory to pin

    :return: IPFS hash of the file
    """

    _LOGGER.debug(f"Start adding {dirname} to Pinata.")
    pinata = PinataPy(pinata_public, pinata_secret)
    ipfs_hash = await hass.async_add_executor_job(_pin_to_pinata, pinata, dirname)
    return ipfs_hash


def _pin_to_pinata(pinata: PinataPy, dirname: str) -> tp.Optional[str]:
    try:
        res = None
        res = pinata.pin_file_to_ipfs(dirname, save_absolute_paths=False)
        ipfs_hash: tp.Optional[str] = res["IpfsHash"]
        _LOGGER.debug(f"Directory {dirname} was added to Pinata with cid: {ipfs_hash}")
        return ipfs_hash
    except Exception as e:
        _LOGGER.error(f"Exception in pinata pin: {e}, pinata response: {res}")

async def pinata_creds_exists(hass: HomeAssistant) -> bool:
    storage_data = await async_load_from_store(hass, STORAGE_PINATA_CREDS)
    res = CONF_PINATA_PUBLIC in storage_data and CONF_PINATA_SECRET in storage_data
    _LOGGER.debug(f"Pinata creds exists: {res}")
    return res