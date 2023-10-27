import logging
import homeassistant.loader as loader
import urllib.parse
from .utils import create_report_notification
from .frontend import async_register_frontend

_LOGGER = logging.getLogger(__name__)

class LoggerHandler(logging.Handler):

    def set_hass(self, hass):
        self.hass = hass

    def emit(self, record):
        if record.name != "custom_components.report_service_robonomics":
            _LOGGER.info(record.name)
            if record.levelname == "ERROR" or record.levelname == "CRITICAL":
                _LOGGER.info(record.msg)
                encoded_description = urllib.parse.quote(record.msg)
                link = f"/report-service?description={encoded_description}"
                service_data = {
                    "message": f"Found an error: {record.msg}. [Click]({link})",
                    "title": "Send Report Service",
                }
                self.hass.async_create_task(create_report_notification(self.hass, service_data))


async def async_setup_entry(hass, entry) -> bool:
    _LOGGER.info("Hello world")
    root_logger = logging.getLogger()
    root_logger_handler = LoggerHandler()
    root_logger_handler.set_hass(hass)
    root_logger.addHandler(root_logger_handler)
    async_register_frontend(hass)
    return True

async def async_setup(hass, config) -> bool:
    return True