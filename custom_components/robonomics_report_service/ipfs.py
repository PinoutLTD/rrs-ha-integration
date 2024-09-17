import logging
import typing as tp
import os
import json

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
            ipfs_hash = await self.hass.async_add_executor_job(
                self._pin_to_pinata, dirname, pinata
            )
            return ipfs_hash

    async def unpin_from_pinata(self, ipfs_hashes_dict: str | dict) -> tp.Optional[str]:
        pinata = await self._get_pinata_with_creds()
        if isinstance(ipfs_hashes_dict, str):
            ipfs_hashes_dict = json.loads(ipfs_hashes_dict)
        if pinata is not None:
            await self.hass.async_add_executor_job(
                self._unpin_from_pinata, ipfs_hashes_dict, pinata
            )

    async def _get_pinata_with_creds(self) -> tp.Optional[PinataPy]:
        storage_data = await async_load_from_store(self.hass, STORAGE_PINATA_CREDS)
        if CONF_PINATA_PUBLIC in storage_data and CONF_PINATA_SECRET in storage_data:
            return PinataPy(
                storage_data[CONF_PINATA_PUBLIC], storage_data[CONF_PINATA_SECRET]
            )

    def _pin_to_pinata(self, dirname: str, pinata: PinataPy) -> tp.Optional[str]:
        try:
            res = None
            dict_with_hashes = {}

            _LOGGER.debug(f"tmp dir: {dirname}")
            file_names = [
                f
                for f in os.listdir(dirname)
                if os.path.isfile(os.path.join(dirname, f))
            ]
            _LOGGER.debug(f"file names: {file_names}")
            for file in file_names:
                path_to_file = f"{dirname}/{file}"
                res = pinata.pin_file_to_ipfs(path_to_file, save_absolute_paths=False)
                ipfs_hash: tp.Optional[str] = res.get("IpfsHash")
                if ipfs_hash:
                    _LOGGER.debug(f"Added file {file} to Pinata. Hash is: {ipfs_hash}")
                    dict_with_hashes[file] = ipfs_hash

                else:
                    _LOGGER.error(f"Can't pin to pinata with responce response: {res}")
            _LOGGER.debug(f"Dict with hashes: {dict_with_hashes}")
            if dict_with_hashes:
                return dict_with_hashes
        except Exception as e:
            _LOGGER.error(f"Exception in pinata pin: {e}, pinata response: {res}")

    def _unpin_from_pinata(self, ipfs_hashes_dict: tp.Dict, pinata: PinataPy) -> None:
        _LOGGER.debug(f"Start removing pins: {ipfs_hashes_dict}")
        for key in ipfs_hashes_dict:
            current_hash: str = ipfs_hashes_dict[key]
            if isinstance(current_hash, str) and current_hash.startswith("Qm"):
                res = pinata.remove_pin_from_ipfs(current_hash)
                _LOGGER.debug(f"Remove response for pin {current_hash}: {res}")
