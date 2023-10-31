import base64
import json
import logging
import os
import urllib.parse

from homeassistant.core import ServiceCall
from substrateinterface import Keypair, KeypairType

from .const import DOMAIN, IPFS_PROBLEM_REPORT_FOLDER, LOG_FILE_NAME, PROBLEM_REPORT_SERVICE, TRACES_FILE_NAME
from .frontend import async_register_frontend
from .robonomics import Robonomics
from .utils import (
    create_encrypted_picture,
    create_notification,
    create_temp_dir_and_copy_files,
    delete_temp_dir,
    encrypt_message,
)

_LOGGER = logging.getLogger(__name__)

PROBLEM_SERVICE_ROBONOMICS_ADDRESS = "4HifM6Cny7bHAdLb5jw3hHV2KabuzRZV8gmHG1eh4PxJakwi"


class LoggerHandler(logging.Handler):
    def set_hass(self, hass):
        self.hass = hass

    def emit(self, record):
        if record.name != "custom_components.report_service_robonomics":
            # _LOGGER.info(record.name)
            if record.levelname == "ERROR" or record.levelname == "CRITICAL":
                _LOGGER.info(record.msg)
                encoded_description = urllib.parse.quote(record.msg)
                link = f"/report-service?description={encoded_description}"
                service_data = {
                    "message": f"Found an error: {record.msg}. [Click]({link})",
                    "title": "Send Report Service",
                }
                self.hass.async_create_task(create_notification(self.hass, service_data))


async def async_setup_entry(hass, entry) -> bool:
    robonomics = Robonomics(hass)
    await robonomics.async_init()
    root_logger = logging.getLogger()
    root_logger_handler = LoggerHandler()
    root_logger_handler.set_hass(hass)
    root_logger.addHandler(root_logger_handler)
    async_register_frontend(hass)

    async def handle_problem_report(call: ServiceCall) -> None:
        try:
            picture_data = call.data.get("picture")
            problem_text = call.data.get("description")
            email = call.data.get("mail")
            phone_number = call.data.get("phone_number", "")
            json_text = {
                "description": problem_text,
                "e-mail": email,
                "phone_number": phone_number,
                "pictures_count": len(picture_data),
            }
            _LOGGER.debug(f"send problem service: {problem_text}")
            hass_config_path = hass.config.path()
            files = []
            if call.data.get("attach_logs"):
                if os.path.isfile(f"{hass_config_path}/{LOG_FILE_NAME}"):
                    files.append(f"{hass_config_path}/{LOG_FILE_NAME}")
                if os.path.isfile(f"{hass_config_path}/{TRACES_FILE_NAME}"):
                    files.append(f"{hass_config_path}/{TRACES_FILE_NAME}")
            tempdir = create_temp_dir_and_copy_files(
                IPFS_PROBLEM_REPORT_FOLDER, files, robonomics.owner_seed, PROBLEM_SERVICE_ROBONOMICS_ADDRESS
            )
            if len(picture_data) != 0:
                i = 1
                for picture in picture_data:
                    decoded_picture_data = base64.b64decode(picture.split(",")[1])
                    picture_path = create_encrypted_picture(
                        decoded_picture_data, i, tempdir, robonomics.owner_seed, PROBLEM_SERVICE_ROBONOMICS_ADDRESS
                    )
                    i += 1
            _LOGGER.debug(f"Tempdir for problem report created: {tempdir}")
            sender_kp = robonomics.owner_account.keypair
            receiver_kp = Keypair(ss58_address=PROBLEM_SERVICE_ROBONOMICS_ADDRESS, crypto_type=KeypairType.ED25519)
            encrypted_json = encrypt_message(json.dumps(json_text), sender_kp, receiver_kp.public_key)
            with open(f"{tempdir}/issue_description.json", "w") as f:
                f.write(encrypted_json)
            #######################################
            # TODO: Add to pinata -> ipsf_hash
            ipfs_hash = "QmRU6Bkrx3DGEQZTk7KBnnYfMoHMbTvx6p7aJqGxVE3pa6"
            #######################################
            await robonomics.send_launch(PROBLEM_SERVICE_ROBONOMICS_ADDRESS, ipfs_hash)
        except Exception as e:
            _LOGGER.debug(f"Exception in send problem service: {e}")
        finally:
            if os.path.exists(tempdir):
                delete_temp_dir(tempdir)

    hass.services.async_register(DOMAIN, PROBLEM_REPORT_SERVICE, handle_problem_report)

    return True


async def async_setup(hass, config) -> bool:
    return True
