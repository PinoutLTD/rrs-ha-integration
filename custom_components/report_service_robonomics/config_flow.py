import voluptuous as vol
import typing as tp

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, ADDRESS

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(ADDRESS): str,
    }
)

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Odoo."""

    VERSION = 1

    async def async_step_user(self, user_input: tp.Optional[dict] = None) -> FlowResult:
        """Handle the initial step of the configuration. Contains user's warnings.
        :param user_input: Dict with the keys from STEP_USER_DATA_SCHEMA and values provided by user
        :return: Service functions from HomeAssistant
        """

        info = {"title": "Robonomics Report Service"}
        device_unique_id = "report_service_robonomics"
        await self.async_set_unique_id(device_unique_id)
        self._abort_if_unique_id_configured()
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA)
        else:
            return self.async_create_entry(title=info["title"], data=user_input)