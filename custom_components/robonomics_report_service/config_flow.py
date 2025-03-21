import typing as tp
import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_EMAIL,
    CONF_SENDER_SEED,
)
from .robonomics import Robonomics
from .rws_registration import RWSRegistrationManager
from .libp2p import LibP2P

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Report Service."""

    VERSION = 1

    def __init__(self):
        self.seed_saved = False

    async def async_step_user(self, user_input: tp.Optional[dict] = None) -> FlowResult:
        """Handle the initial step of the configuration. Contains user's warnings.
        :param user_input: Dict with the keys from STEP_USER_DATA_SCHEMA and values provided by user
        :return: Service functions from HomeAssistant
        """

        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )
        self.user_data = user_input
        sender_seed = Robonomics.generate_seed()
        self.user_data[CONF_SENDER_SEED] = sender_seed
        return await self.async_step_seed()

    async def async_step_seed(self, user_input: dict[str, tp.Any] | None = None):
        if not self.seed_saved:
            self.seed_saved = True
            return self.async_show_form(
                step_id="seed",
                data_schema=vol.Schema({}),
                description_placeholders={"seed": self.user_data[CONF_SENDER_SEED]},
            )
        else:
            robonomics = Robonomics(
                self.hass,
                self.user_data[CONF_SENDER_SEED],
            )
            await robonomics.setup()
            libp2p = LibP2P(robonomics.sender_address)
            # async_register_frontend(hass)
            await RWSRegistrationManager.register(self.hass, robonomics, libp2p, self.user_data[CONF_EMAIL])
            return self.async_create_entry(
                title="Robonomics Report Service", data=self.user_data
            )

