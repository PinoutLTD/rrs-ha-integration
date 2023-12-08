import logging
import urllib.parse

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import ServiceCall, HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_CONTROLLER_SEED,
    CONF_OWNER_ADDRESS,
    DOMAIN,
    ROOT_LOGGER,
    LOGGER_HANDLER,
    PROBLEM_REPORT_SERVICE,
    CONF_OWNER_SEED,
)
from .frontend import async_register_frontend, async_remove_frontend
from .robonomics import Robonomics
from .utils import (
    create_notification,
)
from .service import send_problem_report

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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    robonomics = Robonomics(hass, entry.data[CONF_CONTROLLER_SEED], entry.data[CONF_OWNER_ADDRESS], entry.data[CONF_OWNER_SEED])
    await robonomics.async_init()
    root_logger = logging.getLogger()
    root_logger_handler = LoggerHandler()
    root_logger_handler.set_hass(hass)
    root_logger.addHandler(root_logger_handler)
    hass.data[DOMAIN][ROOT_LOGGER] = root_logger
    hass.data[DOMAIN][LOGGER_HANDLER] = root_logger_handler
    async_register_frontend(hass)

    async def handle_problem_report(call: ServiceCall) -> None:
        await send_problem_report(hass, call, robonomics, entry.data)

    hass.services.async_register(DOMAIN, PROBLEM_REPORT_SERVICE, handle_problem_report)

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
    return True
