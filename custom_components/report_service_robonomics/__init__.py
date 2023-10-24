import logging
import homeassistant.loader as loader
from .utils import create_notification

_LOGGER = logging.getLogger(__name__)

# Configure the root logger
# logging.basicConfig(level=logging.ERROR)

# Create a custom handler
class LoggerHandler(logging.Handler):

    def set_hass(self, hass):
        self.hass = hass

    def emit(self, record):
        # This method is called whenever a log record is produced
        if record.name != "custom_components.report_service_robonomics":
            _LOGGER.info(record.name)
            if record.levelname == "ERROR" or record.levelname == "CRITICAL":
                _LOGGER.info(record.msg)
                service_data = {
                    "message": f"Found an error: {record.msg}. [Click](/redirect-server-controls)",
                    "title": "Send Report Service",
                }
                self.hass.async_create_task(create_notification(self.hass, service_data))


async def async_setup_entry(hass, entry) -> bool:
    _LOGGER.info("Hello world")
    root_logger = logging.getLogger()
    root_logger_handler = LoggerHandler()
    root_logger_handler.set_hass(hass)
    root_logger.addHandler(root_logger_handler)
    return True

async def async_setup(hass, config) -> bool:
    return True