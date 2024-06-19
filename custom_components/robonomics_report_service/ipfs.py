import logging
import typing as tp

from homeassistant.core import HomeAssistant
from pinatapy import PinataPy

from .utils import async_load_from_store
from .const import STORAGE_PINATA_CREDS, CONF_PINATA_PUBLIC, CONF_PINATA_SECRET

_LOGGER = logging.getLogger(__name__)

class IPFS:
    def __init__(self, hass: HomeAssistant):
        self.hass = hass

    async def pin_to_pinata(self, dirname: str) -> tp.Optional[str]:
        pinata = await self._get_pinata_with_creds()
        if pinata is not None:
            ipfs_hash = await self.hass.async_add_executor_job(self._pin_to_pinata, dirname, pinata)
            return ipfs_hash

    async def _get_pinata_with_creds(self) -> tp.Optional[PinataPy]:
        storage_data = await async_load_from_store(self.hass, STORAGE_PINATA_CREDS)
        if CONF_PINATA_PUBLIC in storage_data and CONF_PINATA_SECRET in storage_data:
            return PinataPy(storage_data[CONF_PINATA_PUBLIC], storage_data[CONF_PINATA_SECRET])

    def _pin_to_pinata(self, dirname: str, pinata: PinataPy) -> tp.Optional[str]:
        try:
            res = None
            res = pinata.pin_file_to_ipfs(dirname, save_absolute_paths=False)
            ipfs_hash: tp.Optional[str] = res.get("IpfsHash")
            _LOGGER.debug(f"Directory {dirname} was added to Pinata with cid: {ipfs_hash}")
            return ipfs_hash
        except Exception as e:
            _LOGGER.error(f"Exception in pinata pin: {e}, pinata response: {res}")

