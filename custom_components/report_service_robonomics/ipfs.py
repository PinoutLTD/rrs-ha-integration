import logging
import typing as tp

from homeassistant.core import HomeAssistant
from pinatapy import PinataPy

from .const import STORAGE_PINATA
from .utils import async_load_from_store, async_save_to_store, to_thread

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
    ipfs_hash = await _pin_to_pinata(pinata, dirname)
    storage_data = await async_load_from_store(hass, STORAGE_PINATA)
    if "last_ipfs_hash" in storage_data:
        await _unpin_from_pinata(pinata, storage_data["last_ipfs_hash"])
    storage_data["last_ipfs_hash"] = ipfs_hash
    await async_save_to_store(hass, STORAGE_PINATA, storage_data)
    return ipfs_hash


@to_thread
def _pin_to_pinata(pinata: PinataPy, dirname: str) -> tp.Optional[str]:
    try:
        res = None
        res = pinata.pin_file_to_ipfs(dirname, save_absolute_paths=False)
        ipfs_hash: tp.Optional[str] = res["IpfsHash"]
        _LOGGER.debug(f"Directory {dirname} was added to Pinata with cid: {ipfs_hash}")
        return ipfs_hash
    except Exception as e:
        _LOGGER.error(f"Exception in pinata pin: {e}, pinata response: {res}")


@to_thread
def _unpin_from_pinata(pinata: PinataPy, ipfs_hash: str) -> None:
    try:
        pinata.remove_pin_from_ipfs(ipfs_hash)
        _LOGGER.debug(f"Hash {ipfs_hash} was unpinned from Pinata")
    except Exception as e:
        _LOGGER.debug(f"Exception in unpinning file from Pinata: {e}")
