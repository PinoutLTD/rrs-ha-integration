import abc
from homeassistant.core import HomeAssistant

from ...const import DOMAIN, PROBLEM_REPORT_SERVICE, CONF_EMAIL, CONF_PHONE_NUMBER
from .utils.problem_type import ProblemType


class ErrorSource(abc.ABC):
    def __init__(self, hass: HomeAssistant):
        self.hass = hass

    @abc.abstractmethod
    def setup(self):
        pass

    @abc.abstractmethod
    def remove(self):
        pass

    async def _run_report_service(
        self,
        description: str,
        error_type: ProblemType,
        problem_source: str,
        repeated_error: bool = False,
    ):
        formatted_description = {
            "description": description,
            "type": error_type.value,
            "source": problem_source,
        }
        service_data = {
            "description": formatted_description,
            "mail": self.hass.data[DOMAIN][CONF_EMAIL],
            "only_description": repeated_error,
        }
        if CONF_PHONE_NUMBER in self.hass.data[DOMAIN]:
            service_data["phone_number"] = self.hass.data[DOMAIN][CONF_PHONE_NUMBER]
        await self.hass.services.async_call(
            DOMAIN, PROBLEM_REPORT_SERVICE, service_data=service_data
        )
