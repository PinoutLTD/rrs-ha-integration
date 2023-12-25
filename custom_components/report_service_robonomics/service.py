import base64
import logging
import os
import json

from substrateinterface import Keypair, KeypairType
from homeassistant.core import ServiceCall, HomeAssistant

from .const import (
    LOG_FILE_NAME,
    TRACES_FILE_NAME,
    IPFS_PROBLEM_REPORT_FOLDER,
    PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
    CONF_PINATA_PUBLIC,
    CONF_PINATA_SECRET,
)
from .ipfs import pin_to_pinata
from .utils import (
    create_temp_dir_and_copy_files,
    create_encrypted_picture,
    encrypt_message,
    delete_temp_dir,
)
from .robonomics import Robonomics


_LOGGER = logging.getLogger(__name__)


async def send_problem_report(
    hass: HomeAssistant, call: ServiceCall, robonomics: Robonomics, entry_data
) -> None:
    try:
        picture_data = call.data.get("picture")
        problem_text = call.data.get("description")
        phone_number = call.data.get("phone_number", "")
        json_text = {
            "description": problem_text,
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
            IPFS_PROBLEM_REPORT_FOLDER,
            files,
            robonomics.controller_seed,
            PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
        )
        if len(picture_data) != 0:
            i = 1
            for picture in picture_data:
                decoded_picture_data = base64.b64decode(picture.split(",")[1])
                picture_path = create_encrypted_picture(
                    decoded_picture_data,
                    i,
                    tempdir,
                    robonomics.controller_seed,
                    PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
                )
                i += 1
        _LOGGER.debug(f"Tempdir for problem report created: {tempdir}")
        sender_kp = robonomics.controller_account.keypair
        receiver_kp = Keypair(
            ss58_address=PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
            crypto_type=KeypairType.ED25519,
        )
        encrypted_json = encrypt_message(
            json.dumps(json_text), sender_kp, receiver_kp.public_key
        )
        with open(f"{tempdir}/issue_description.json", "w") as f:
            f.write(encrypted_json)
        ipfs_hash = await pin_to_pinata(
            hass,
            tempdir,
            entry_data[CONF_PINATA_PUBLIC],
            entry_data[CONF_PINATA_SECRET],
        )
        await robonomics.send_launch(PROBLEM_SERVICE_ROBONOMICS_ADDRESS, ipfs_hash)
    except Exception as e:
        _LOGGER.debug(f"Exception in send problem service: {e}")
    finally:
        if os.path.exists(tempdir):
            delete_temp_dir(tempdir)
