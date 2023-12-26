import logging
import typing as tp

from homeassistant.core import HomeAssistant
from pinatapy import PinataPy

from .utils import to_thread

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

