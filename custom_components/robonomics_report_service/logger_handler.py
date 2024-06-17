import logging
import asyncio

_LOGGER = logging.getLogger(__name__)

from homeassistant.core import HomeAssistant

from .utils import create_link_for_notification, create_notification
from .const import DOMAIN, ROOT_LOGGER, LOGGER_HANDLER

class LoggerHandler(logging.Handler):
    def setup(self, hass: HomeAssistant):
        self.hass = hass
        root_logger = logging.getLogger()
        root_logger.addHandler(self)
        self.hass.data[DOMAIN][ROOT_LOGGER] = root_logger
        self.hass.data[DOMAIN][LOGGER_HANDLER] = self

    def emit(self, record):
        if record.name != "custom_components.report_service_robonomics":
            if record.levelname == "ERROR" or record.levelname == "CRITICAL":
                _LOGGER.info(record.msg)
                error_msg = f"{record.name}: {record.msg}"
                link = create_link_for_notification(error_msg)
                service_data = {
                    "message": f"Found an error: {record.msg} from {record.name}. [Click]({link})",
                    "title": "Send Report Service",
                }
                asyncio.run_coroutine_threadsafe(create_notification(self.hass, service_data), self.hass.loop)