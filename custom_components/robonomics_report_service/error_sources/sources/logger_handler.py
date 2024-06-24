import logging
import asyncio

_LOGGER = logging.getLogger(__name__)

from homeassistant.core import HomeAssistant, callback

from .error_source import ErrorSource
from ...const import DOMAIN

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
        if DOMAIN not in record.name:
            if record.levelname == "ERROR" or record.levelname == "CRITICAL" or record.levelname == "WARNING":
                _LOGGER.debug(f"New error message: {record.msg}")
                error_msg = f"{record.name}: {record.msg}"
                asyncio.run_coroutine_threadsafe(
                    self._run_report_service(error_msg), self.hass.loop
                )
    