import abc
from homeassistant.core import HomeAssistant

from ...const import DOMAIN, PROBLEM_REPORT_SERVICE, CONF_EMAIL, CONF_PHONE_NUMBER


class ErrorSource(abc.ABC):
    def __init__(self, hass: HomeAssistant):
        self.hass = hass

    @abc.abstractmethod
    def setup(self):
        pass

    @abc.abstractmethod
    def remove(self):
        pass

    async def _run_report_service(self, description: str):
        service_data = {
            "description": description,
            "mail": self.hass.data[DOMAIN][CONF_EMAIL],
            "attach_logs": True,
        }
        if CONF_PHONE_NUMBER in self.hass.data[DOMAIN]:
            service_data["phone_number"] = self.hass.data[DOMAIN][CONF_PHONE_NUMBER]
        await self.hass.services.async_call(
            DOMAIN, PROBLEM_REPORT_SERVICE, service_data=service_data
        )
