import logging
import asyncio
from datetime import timedelta

_LOGGER = logging.getLogger(__name__)

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .error_source import ErrorSource
from .utils.message_formatter import MessageFormatter
from ...const import DOMAIN

WARNING_SENDING_TIMEOUT = timedelta(hours=4)

class LoggerHandler(logging.Handler, ErrorSource):
    def __init__(self, hass: HomeAssistant):
        logging.Handler.__init__(self)
        ErrorSource.__init__(self, hass)
        self.unsub_timer = None
        self.root_logger = None
        self._warning_messages = []

    @callback
    def setup(self):
        self.root_logger = logging.getLogger()
        self.root_logger.addHandler(self)
        self.unsub_timer = async_track_time_interval(
            self.hass,
            self._send_warnings,
            WARNING_SENDING_TIMEOUT,
        )

    @callback
    def remove(self):
        self.root_logger.removeHandler(self)
        if self.unsub_timer is not None:
            self.unsub_timer()

    def emit(self, record):
        if DOMAIN not in record.name:
            if record.levelname == "ERROR" or record.levelname == "CRITICAL":
                _LOGGER.debug(f"New error message: {record.msg}")
                error_msg = f"{record.name} - {record.levelname}: {record.msg}"
                asyncio.run_coroutine_threadsafe(
                    self._run_report_service(error_msg, "errors"), self.hass.loop
                )
            elif record.levelname == "WARNING":
                self._warning_messages.append(f"{record.name} - {record.levelname}: {record.msg}")

    async def _send_warnings(self, _ = None) -> None:
        if len(self._warning_messages) > 0:
            _LOGGER.debug(f"Got {len(self._warning_messages)} warning messages, start sending report")
            warnings = self._warning_messages.copy()
            self._warning_messages.clear()
            message = MessageFormatter.format_warnins_message(warnings)
            await self._run_report_service(message, "warnings")
        else:
            _LOGGER.debug("Haven't got any warning messages during timeout")

    