import logging
import asyncio

_LOGGER = logging.getLogger(__name__)

from homeassistant.core import HomeAssistant, callback

from .error_source import ErrorSource

class LoggerHandler(logging.Handler, ErrorSource):
    def __init__(self, hass: HomeAssistant):
        logging.Handler.__init__(self)
        ErrorSource.__init__(self, hass)
        self.root_logger = None

    @callback
    def setup(self):
        self.root_logger = logging.getLogger()
        self.root_logger.addHandler(self)

    @callback
    def remove(self):
        self.root_logger.removeHandler(self)

    def emit(self, record):
        if record.name != "custom_components.report_service_robonomics":
            if record.levelname == "ERROR" or record.levelname == "CRITICAL":
                _LOGGER.debug(record.msg)
                error_msg = f"{record.name}: {record.msg}"
                asyncio.run_coroutine_threadsafe(
                    self._run_report_service(error_msg), self.hass.loop
                ).result()
    