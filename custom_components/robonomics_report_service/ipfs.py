import json
import os
from dataclasses import dataclass
from typing import cast

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pinatapy import PinataPy

from .const import CONF_PINATA_PUBLIC, CONF_PINATA_SECRET, CREDS_STORAGE_KEY
from .exceptions import IPFSError, PinataKeysRevokedError, StorageError
from .utils.ha_storage import async_load_from_store

IpfsHashes = dict[str, str]

PINATA_TEST_AUTHENTICATION_URL = "https://api.pinata.cloud/data/testAuthentication"


async def async_check_pinata_keys(hass: HomeAssistant, public: str, secret: str) -> str | None:
    """Ask Pinata whether the key pair is valid; returns an error key or None.

    This uploads nothing. It catches a mistyped or revoked key and a JWT pasted
    as the secret; a valid key that lacks the pinning scope still passes, and
    that case is reported, with Pinata's own message, by the first upload.
    """

    try:
        async with async_get_clientsession(hass).get(
            PINATA_TEST_AUTHENTICATION_URL,
            headers={"pinata_api_key": public, "pinata_secret_api_key": secret},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status == 200:
                return None
            if response.status in (401, 403):
                return "invalid_pinata_keys"
            return "pinata_unavailable"
    except (aiohttp.ClientError, TimeoutError):
        return "pinata_unavailable"


@dataclass(frozen=True)
class UnpinResult:
    """Counting files in unpinning"""

    attempted: int
    succeeded: int
    failed: int
    failed_hashes: tuple[str, ...] = ()


class IPFS:
    """Class for handling IPFS and Pinata functionality"""

    def __init__(self, hass: HomeAssistant):
        self.hass = hass

    async def pin_files_from_dir_to_pinata(self, dir_name: str) -> IpfsHashes:
        """
        Upload and pin files from directory to Pinata and get their IPFS hashes
        """
        pinata = await self._get_pinata_with_creds()

        return await self.hass.async_add_executor_job(
            self._pin_files_from_dir_to_pinata, dir_name, pinata
        )

    async def pin_file_to_pinata(self, file_path: str) -> str:
        """Upload and pin one file to Pinata and get its hash"""
        pinata = await self._get_pinata_with_creds()
        return await self.hass.async_add_executor_job(self._pin_file_to_pinata, file_path, pinata)

    async def unpin_files_from_pinata(self, payload: str | IpfsHashes) -> UnpinResult:
        """Unpin IPFS file from Pinata"""

        try:
            pinata = await self._get_pinata_with_creds()
        except IPFSError:
            return UnpinResult(attempted=0, succeeded=0, failed=0)

        ipfs_hashes = self._normalize_unpin_payload(payload)

        if not ipfs_hashes:
            return UnpinResult(attempted=0, succeeded=0, failed=0)

        return await self.hass.async_add_executor_job(
            self._unpin_files_from_pinata, ipfs_hashes, pinata
        )

    async def _get_pinata_with_creds(self) -> PinataPy:
        try:
            storage_data = await async_load_from_store(self.hass, CREDS_STORAGE_KEY)
        except StorageError as e:
            raise IPFSError("Failed to load Pinata credentials") from e

        try:
            pub = storage_data[CONF_PINATA_PUBLIC]
            sec = storage_data[CONF_PINATA_SECRET]
        except KeyError as e:
            raise IPFSError("Pinata credentials are missing") from e

        return PinataPy(pub, sec)

    def _pin_files_from_dir_to_pinata(self, dir_name: str, pinata: PinataPy) -> IpfsHashes:

        dict_with_hashes: IpfsHashes = {}

        try:
            file_names = [
                f for f in os.listdir(dir_name) if os.path.isfile(os.path.join(dir_name, f))
            ]
        except OSError as e:
            raise IPFSError(f"Cannot list directory for pinning: {dir_name}") from e

        for file in file_names:
            path_to_file = os.path.join(dir_name, file)

            try:
                res = pinata.pin_file_to_ipfs(path_to_file, save_absolute_paths=False)
            except Exception as e:
                raise IPFSError(f"Pinata pin_file_to_ipfs failed for file: {file}") from e

            if not isinstance(res, dict):
                raise IPFSError(f"Pinata returned unexpected response for file: {file}")

            ipfs_hash = res.get("IpfsHash")

            if isinstance(ipfs_hash, str) and ipfs_hash:
                dict_with_hashes[file] = ipfs_hash
                continue

            status = res.get("status")
            text = res.get("text", "")

            if status == 403 and isinstance(text, str) and "API_KEY_REVOKED" in text:
                raise PinataKeysRevokedError("Pinata API key was revoked")

            raise IPFSError(f"Pinata did not return IpfsHash for file: {file}")

        if not dict_with_hashes:
            raise IPFSError("No files were pinned to Pinata")

        return dict_with_hashes

    def _pin_file_to_pinata(self, file_path: str, pinata: PinataPy) -> str:

        if not os.path.isfile(file_path):
            raise IPFSError(f"File for uploading to Pinata not found: {file_path}")

        try:
            res = pinata.pin_file_to_ipfs(file_path, save_absolute_paths=False)
        except Exception as e:
            raise IPFSError(f"Pinata pin_file_to_ipfs failed for: {file_path}") from e

        if not isinstance(res, dict):
            raise IPFSError("Pinata returned unexpected response type")

        ipfs_hash = res.get("IpfsHash")

        if isinstance(ipfs_hash, str) and ipfs_hash:
            return ipfs_hash

        status = res.get("status")
        text = res.get("text", "")

        if status == 403 and isinstance(text, str) and "API_KEY_REVOKED" in text:
            raise PinataKeysRevokedError("Pinata API key was revoked")

        # Say what Pinata answered: a key without the pinning scope and a
        # JWT pasted as the secret both end up here, and look identical
        # without the status and message.
        detail = f"status={status}" if status is not None else "no status"
        if isinstance(text, str) and text:
            detail += f", response={text[:300]}"
        raise IPFSError(f"Pinata did not return IpfsHash ({detail})")

    def _normalize_unpin_payload(self, payload: str | IpfsHashes) -> IpfsHashes | None:
        # If IPFS hashes provided in dict
        if isinstance(payload, dict):
            return self._normalize_hash_dict(payload)

        # If IPFS hashes provided in str
        s = payload.strip()

        if not s:
            return None

        if s.startswith("{"):
            try:
                loaded = json.loads(s)
            except json.JSONDecodeError:
                return None
            if not isinstance(loaded, dict):
                return None
            return self._normalize_hash_dict(cast(IpfsHashes, loaded))

        # If str is just one hash
        return {"archive": s}

    def _normalize_hash_dict(self, d: IpfsHashes) -> IpfsHashes | None:
        normalized: IpfsHashes = {}
        for k, v in d.items():
            if not isinstance(v, str):
                continue
            cid = v.strip()
            if cid:
                normalized[k] = cid
        return normalized or None

    def _unpin_files_from_pinata(
        self, ipfs_hashes_dict: IpfsHashes, pinata: PinataPy
    ) -> UnpinResult:
        failed: list[str] = []
        attempted = 0
        succeeded = 0

        for current_hash in ipfs_hashes_dict.values():
            if not (isinstance(current_hash, str) and current_hash):
                continue

            attempted += 1
            try:
                pinata.remove_pin_from_ipfs(current_hash)
                succeeded += 1
            except Exception:
                failed.append(current_hash)

        return UnpinResult(
            attempted=attempted,
            succeeded=succeeded,
            failed=len(failed),
            failed_hashes=tuple(failed[:10]),
        )
