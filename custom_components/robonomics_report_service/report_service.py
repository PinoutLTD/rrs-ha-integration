import base64
import logging
import asyncio
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
from .ipfs import IPFS, PinataKeysRewoked
from .utils import (
    create_temp_dir_with_encrypted_files,
    encrypt_message,
    delete_temp_dir,
    get_tempdir_filenames,
)
from .robonomics import Robonomics
from .libp2p import LibP2P
from .report_model import ReportData, ReportStatus
from .rws_registration import RWSRegistrationManager


_LOGGER = logging.getLogger(__name__)



class ReportService:
    def __init__(self, hass: HomeAssistant, robonomics: Robonomics, libp2p: LibP2P):
        self.hass = hass
        self.robonomics = robonomics
        self.ipfs = IPFS(hass)
        self.libp2p = libp2p
        self._pending_reports: dict[str, ReportData] = {}
        self._requesting_new_pinata_creds = False

    async def register(self) -> None:
        self.hass.services.async_register(
            DOMAIN, PROBLEM_REPORT_SERVICE, self.send_problem_report
        )
        self.libp2p.register_report_handler(self._handle_report_response)
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
            data_to_send = await self._create_data_for_errors_with_logs(call.data)
        if data_to_send is not None:
            new_report = ReportData.create(data_to_send, call.data.get("description"))
            self._pending_reports[new_report.id] = new_report
            await self.libp2p.send_report(
                new_report.encrypted_data, new_report.id
            )

    async def _handle_report_response(self, report_id: str, response: dict) -> None:
        if not response["datalog"]:
            self._pending_reports.pop(report_id)
            _LOGGER.debug(f"Report {report_id} is finished without datalog")
        else:
            report = self._pending_reports.get(report_id)
            _LOGGER.debug(f"Report {report_id} will be sent in datalog, report: {report}")
            if report:
                asyncio.ensure_future(self._send_report_to_datalog(report, response["ticket_ids"]))

    async def _send_report_to_datalog(self, report: ReportData, ticket_ids: list) -> None:
        if "home-assistant.log" in report.encrypted_data:
            _LOGGER.debug(f"Report {report.id} has encrypted logs")
            await self.robonomics.send_datalog(report.encrypted_data)
        else:
            _LOGGER.debug(f"Report {report.id} doesn't have encrypted logs")
            data_to_send = await self._create_data_for_errors_with_logs({"description": report.description})
            data_to_send["ticket_ids"] = ticket_ids.copy()
            await self.robonomics.send_datalog(data_to_send)

    async def _create_data_for_errors_with_logs(self, issue_description: dict) -> dict:
        try:
            tempdir = await self._create_temp_dir_with_report_data(issue_description)
            while self._requesting_new_pinata_creds:
                await asyncio.sleep(1)
            data_to_send = await self.ipfs.pin_to_pinata(tempdir)
        except PinataKeysRewoked:
            self._requesting_new_pinata_creds = True
            await RWSRegistrationManager.request_new_pinata_creds(self.hass, self.robonomics, self.libp2p)
            self._requesting_new_pinata_creds = False
            data_to_send = await self.ipfs.pin_to_pinata(tempdir)
        finally:
            await self._remove_tempdir(tempdir)
        return data_to_send

    def _create_data_for_repeated_errors(self, description: dict) -> dict:
        encrypted = self.robonomics.encrypt_for_integrator({"description": description})
        return {"issue_description.json": encrypted}

    async def _create_temp_dir_with_report_data(self, issue_description: dict) -> str:
        files = self._get_logs_files()
        tempdir: str = await self._async_create_temp_dir_with_encrypted_files(files)
        await self._async_add_description_json(issue_description, tempdir)
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

    async def _async_add_description_json(self, call_data: dict, tempdir: str) -> None:
        await self.hass.async_add_executor_job(
            self._add_description_json, call_data, tempdir
        )

    def _add_description_json(self, call_data: dict, tempdir: str) -> None:
        problem_text = call_data.get("description")
        json_description = {
            "description": problem_text,
        }
        encrypted_description = self.robonomics.multi_device_encrypt(json_description)
        with open(f"{tempdir}/issue_description.json", "w") as f:
            f.write(encrypted_description)

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
