import base64
import logging
import os
import json
import typing as tp

from homeassistant.core import ServiceCall, HomeAssistant

from .const import (
    LOG_FILE_NAME,
    TRACES_FILE_NAME,
    IPFS_PROBLEM_REPORT_FOLDER,
    PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
    DOMAIN,
    PROBLEM_REPORT_SERVICE,
)
from .ipfs import IPFS
from .utils import (
    create_temp_dir_with_encrypted_files,
    create_encrypted_picture,
    encrypt_message,
    delete_temp_dir,
)
from .robonomics import Robonomics


_LOGGER = logging.getLogger(__name__)


class ReportService:
    def __init__(self, hass: HomeAssistant, robonomics: Robonomics):
        self.hass = hass
        self.robonomics = robonomics
        self.ipfs = IPFS(hass)

    def register(self) -> None:
        self.hass.services.async_register(DOMAIN, PROBLEM_REPORT_SERVICE, self.send_problem_report)

    async def send_problem_report(self, call: ServiceCall) -> None:
        _LOGGER.debug(f"send problem service: {call.data.get('description')}")
        tempdir = await self._create_temp_dir_with_report_data(call)
        ipfs_hash = await self.ipfs.pin_to_pinata(tempdir)
        self._remove_tempdir(tempdir)
        if ipfs_hash is not None:
            await self.robonomics.send_datalog(ipfs_hash)

    async def _create_temp_dir_with_report_data(self, call: ServiceCall) -> str:
        if call.data.get("attach_logs"):
            files = self._get_logs_files()
        else:
            files = []
        tempdir: str = await self._async_create_temp_dir_with_encrypted_files(files)
        await self._async_add_pictures_if_exists(tempdir, call.data.get("picture"))
        await self._async_add_description_json(call.data, tempdir)
        return tempdir

    def _get_logs_files(self) -> tp.List[str]:
        hass_config_path = self.hass.config.path()
        files = []
        if os.path.isfile(f"{hass_config_path}/{LOG_FILE_NAME}"):
            files.append(f"{hass_config_path}/{LOG_FILE_NAME}")
        if os.path.isfile(f"{hass_config_path}/{TRACES_FILE_NAME}"):
            files.append(f"{hass_config_path}/{TRACES_FILE_NAME}")
        return files

    async def _async_create_temp_dir_with_encrypted_files(
        self, files: tp.List[str]
    ) -> str:
        return await self.hass.async_add_executor_job(
            self._create_temp_dir_with_encrypted_files, files
        )

    def _create_temp_dir_with_encrypted_files(self, files: tp.List[str]) -> str:
        return create_temp_dir_with_encrypted_files(
            IPFS_PROBLEM_REPORT_FOLDER,
            files,
            self.robonomics.sender_seed,
            PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
        )

    async def _async_add_pictures_if_exists(self, tempdir: str, picture_data) -> None:
        await self.hass.async_add_executor_job(
            self._add_pictures_if_exists, tempdir, picture_data
        )

    def _add_pictures_if_exists(self, tempdir: str, picture_data) -> None:
        if picture_data is not None:
            i = 1
            for picture in picture_data:
                decoded_picture_data = base64.b64decode(picture.split(",")[1])
                create_encrypted_picture(
                    decoded_picture_data,
                    i,
                    tempdir,
                    self.robonomics.sender_seed,
                    PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
                )
                i += 1

    async def _async_add_description_json(self, call_data: dict, tempdir: str) -> None:
        await self.hass.async_add_executor_job(self._add_description_json, call_data, tempdir)

    def _add_description_json(self, call_data: dict, tempdir: str) -> None:
        picture_data = call_data.get("picture", [])
        problem_text = call_data.get("description")
        phone_number = call_data.get("phone_number", "")
        json_description = {
            "description": problem_text,
            "phone_number": phone_number,
            "pictures_count": len(picture_data),
        }
        encrypted_description = self._encrypt_json(json_description)
        with open(f"{tempdir}/issue_description.json", "w") as f:
            f.write(encrypted_description)

    def _encrypt_json(self, data: dict) -> str:
        return encrypt_message(
            json.dumps(data),
            sender_seed=self.robonomics.sender_seed,
            recipient_address=PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
        )

    def _remove_tempdir(self, tempdir: str) -> None:
        if os.path.exists(tempdir):
            delete_temp_dir(tempdir)

