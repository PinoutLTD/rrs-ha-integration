import asyncio
import logging
import urllib.parse
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import ServiceCall, HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_CONTROLLER_SEED,
    CONF_EMAIL,
    CONF_OWNER_ADDRESS,
    DOMAIN,
    ROOT_LOGGER,
    LOGGER_HANDLER,
    PROBLEM_REPORT_SERVICE,
    CONF_OWNER_SEED,
    STORAGE_PINATA_CREDS,
    CONF_PINATA_PUBLIC,
    CONF_PINATA_SECRET,
    ROBONOMICS,
    RWS_CHECK_UNSUB,
)
from .frontend import async_register_frontend, async_remove_frontend
from .robonomics import Robonomics
from .utils import (
    create_notification,
    async_load_from_store,
    async_remove_store,
    ReportServiceStatus,
    set_service_status,
)
from .service import send_problem_report
from .libp2p import get_pinata_creds
from .websocket import async_register_websocket_commands
from .ipfs import pinata_creds_exists

_LOGGER = logging.getLogger(__name__)


class LoggerHandler(logging.Handler):
    def set_hass(self, hass: HomeAssistant):
        self.hass = hass

    def emit(self, record):
        if record.name != "custom_components.report_service_robonomics":
            if record.levelname == "ERROR" or record.levelname == "CRITICAL":
                _LOGGER.info(record.msg)
                error_msg = f"{record.name}: {record.msg}"
                encoded_description = urllib.parse.quote(error_msg)
                link = f"/report-service?description={encoded_description}"
                service_data = {
                    "message": f"Found an error: {record.msg} from {record.name}. [Click]({link})",
                    "title": "Send Report Service",
                }
                self.hass.async_create_task(
                    create_notification(self.hass, service_data)
                )


async def wait_for_pinata_creds(hass: HomeAssistant, entry: ConfigEntry):
    if not await pinata_creds_exists(hass):
        _LOGGER.debug("Pinata credentials are not in storage")
        while not await get_pinata_creds(
            hass,
            entry.data[CONF_CONTROLLER_SEED],
            entry.data[CONF_EMAIL],
            entry.data[CONF_OWNER_ADDRESS],
        ):
            await asyncio.sleep(0.5)
    else:
        _LOGGER.debug("Pinata credentials are in storage")
    await hass.data[DOMAIN][ROBONOMICS].async_init()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    set_service_status(hass, ReportServiceStatus.WaitPinataCreds)
    hass.data[DOMAIN][ROBONOMICS] = Robonomics(
        hass,
        entry.data[CONF_CONTROLLER_SEED],
        entry.data[CONF_OWNER_ADDRESS],
        entry.data.get(CONF_OWNER_SEED),
    )
    root_logger = logging.getLogger()
    root_logger_handler = LoggerHandler()
    root_logger_handler.set_hass(hass)
    root_logger.addHandler(root_logger_handler)
    hass.data[DOMAIN][ROOT_LOGGER] = root_logger
    hass.data[DOMAIN][LOGGER_HANDLER] = root_logger_handler
    async_register_websocket_commands(hass)
    async_register_frontend(hass)

    async def check_rws_active(data=None):
        if ROBONOMICS in hass.data[DOMAIN]:
            if not await hass.data[DOMAIN][
                ROBONOMICS
            ].get_rws_left_days() or not await pinata_creds_exists(hass):
                # Delete pinata creds
                await async_remove_store(hass, STORAGE_PINATA_CREDS)
                entry.async_create_task(hass, wait_for_pinata_creds(hass, entry))

    async def handle_problem_report(call: ServiceCall) -> None:
        storage_data = await async_load_from_store(hass, STORAGE_PINATA_CREDS)
        if (
            CONF_PINATA_PUBLIC in storage_data
            and CONF_PINATA_SECRET in storage_data
            and ROBONOMICS in hass.data[DOMAIN]
        ):
            await send_problem_report(
                hass, call, hass.data[DOMAIN][ROBONOMICS], storage_data
            )

    await check_rws_active()
    hass.services.async_register(DOMAIN, PROBLEM_REPORT_SERVICE, handle_problem_report)
    # entry.async_create_task(hass, wait_for_pinata_creds(hass, entry))
    hass.data[DOMAIN][RWS_CHECK_UNSUB] = async_track_time_interval(
        hass,
        check_rws_active,
        timedelta(days=1),
    )

    return True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.
    It calls during integration's removing.

    :param hass: HomeAssistant instance
    :param entry: Data from config

    :return: True if all unload event were success
    """
    hass.data[DOMAIN][ROOT_LOGGER].removeHandler(hass.data[DOMAIN][LOGGER_HANDLER])
    async_remove_frontend(hass)
    hass.data[DOMAIN][RWS_CHECK_UNSUB]()
    return True
