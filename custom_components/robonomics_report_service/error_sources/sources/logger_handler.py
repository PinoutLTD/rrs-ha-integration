import logging

_LOGGER = logging.getLogger(__name__)

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.components.system_log import DOMAIN as SYSTEM_LOG_DOMAIN
from homeassistant.components.system_log import EVENT_SYSTEM_LOG

from .error_source import ErrorSource
from .utils.problem_type import ProblemType
from ...const import DOMAIN


class LoggerHandler(ErrorSource):
    def __init__(self, hass: HomeAssistant):
        ErrorSource.__init__(self, hass)
        self.unsub = None
        self.hass.data[SYSTEM_LOG_DOMAIN].fire_event = True

    @callback
    def setup(self):
        self.unsub = self.hass.bus.async_listen(EVENT_SYSTEM_LOG, self.new_log)

    @callback
    def remove(self):
        if self.unsub is not None:
            self.unsub()

    async def new_log(self, record_event: Event):
        _LOGGER.debug(f"New log: {record_event.data}, type: {type(record_event.data)}")
        record = record_event.data
        if DOMAIN not in record["name"]:
            record_type = self._get_record_type(record)
            if record_type:
                repeated_error = self._repeated_error(record)
                _LOGGER.debug(f"New {record_type} message: {record['message']}")
                error_msg = (
                    f"{record['name']} - {record['level']}: {record['message'][0]}"
                )
                error_source = record["source"]
                await self._run_report_service(
                    error_msg, record_type, error_source, repeated_error
                )

    def _get_record_type(self, record: dict) -> ProblemType | None:
        if record["level"] == "ERROR" or record["level"] == "CRITICAL":
            record_type = ProblemType.Errors
        elif record["level"] == "WARNING":
            record_type = ProblemType.Warnings
        else:
            record_type = None
        return record_type

    def _repeated_error(self, record: dict) -> bool:
        logs = self.hass.data[SYSTEM_LOG_DOMAIN].records.to_list()
        for log in logs:
            if log["source"] == record["source"]:
                return log["count"] > 1
        else:
            return False
