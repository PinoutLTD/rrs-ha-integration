import base64
import logging
import os
import json
import typing as tp

from homeassistant.core import ServiceCall, HomeAssistant
from homeassistant.components.system_log import DOMAIN as SYSTEM_LOG_DOMAIN

from .const import (
    LOG_FILE_NAME,
    TRACES_FILE_NAME,
    IPFS_PROBLEM_REPORT_FOLDER,
    PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
    DOMAIN,
    PROBLEM_REPORT_SERVICE,
    SERVICE_PAID,
)
from .ipfs import IPFS
from .utils import (
    create_temp_dir_with_encrypted_files,
    create_encrypted_picture,
    encrypt_message,
    delete_temp_dir,
    get_tempdir_filenames,
)
from .robonomics import Robonomics
from .libp2p import LibP2P


_LOGGER = logging.getLogger(__name__)


class ReportService:
    def __init__(self, hass: HomeAssistant, robonomics: Robonomics, libp2p: LibP2P):
        self.hass = hass
        self.robonomics = robonomics
        self.ipfs = IPFS(hass)
        self.libp2p = libp2p

    async def register(self) -> None:
        self.hass.services.async_register(
            DOMAIN, PROBLEM_REPORT_SERVICE, self.send_problem_report
        )
        await self._clear_tempdirs()

    async def send_problem_report(self, call: ServiceCall) -> None:
        _LOGGER.debug(
            f"send problem service with logs: {not call.data.get('only_description')}: {call.data.get('description')}"
        )
        if call.data.get("only_description"):
            data_to_send = self._create_data_for_repeated_errors(
                call.data.get("description")
            )
        else:
            try:
                tempdir = await self._create_temp_dir_with_report_data(call)
                data_to_send = await self.ipfs.pin_to_pinata(tempdir)
            finally:
                await self._remove_tempdir(tempdir)
        if data_to_send is not None:
            if SERVICE_PAID and not call.data.get("only_description"):
                await self.robonomics.send_datalog(json.dumps(data_to_send))
            else:
                await self.libp2p.send_report(
                    data_to_send, self.robonomics.sender_address
                )

    def _create_data_for_repeated_errors(self, description: dict) -> dict:
        encrypted = json.loads(self._encrypt_json({"description": description}))
        return {"issue_description.json": encrypted}

    async def _create_temp_dir_with_report_data(self, call: ServiceCall) -> str:
        files = self._get_logs_files()
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
        await self.hass.async_add_executor_job(
            self._add_description_json, call_data, tempdir
        )

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

    async def _clear_tempdirs(self) -> None:
        dirs_to_delete = await self.hass.async_add_executor_job(
            get_tempdir_filenames, IPFS_PROBLEM_REPORT_FOLDER
        )
        for dirname in dirs_to_delete:
            await self._remove_tempdir(dirname)

    async def _remove_tempdir(self, tempdir: str) -> None:
        if os.path.exists(tempdir):
            await self.hass.async_add_executor_job(delete_temp_dir, tempdir)
            _LOGGER.debug(f"Temp directory {tempdir} was deleted")
