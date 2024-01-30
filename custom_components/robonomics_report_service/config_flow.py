import typing as tp
import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_EMAIL,
    CONF_OWNER_SEED,
    STORAGE_ACCOUNT_SEED,
    CONF_OWNER_ADDRESS,
    CONF_CONTROLLER_SEED,
)
from .utils import (
    async_load_from_store,
    async_save_to_store,
)
from .robonomics import create_account, get_address_for_seed

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
        self.paid = False

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
        await self._get_or_create_accounts()
        return self.async_create_entry(
            title="Robonomics Report Service", data=self.user_data
        )

    async def _get_or_create_accounts(self):
        storage_data = await async_load_from_store(self.hass, STORAGE_ACCOUNT_SEED)
        # If Robonomics integration was configured, there will be controller seed and owner address in the storage
        if (
            CONF_CONTROLLER_SEED in storage_data
            and CONF_OWNER_ADDRESS in storage_data
        ):
            controller_seed = storage_data[CONF_CONTROLLER_SEED]
            owner_address = storage_data[CONF_OWNER_ADDRESS]
            owner_seed = storage_data.get(CONF_OWNER_SEED)
        else:
            controller_seed, _ = create_account()
            owner_seed, owner_account = create_account()
            owner_address = owner_account.get_address()
            storage_data[CONF_CONTROLLER_SEED] = controller_seed
            storage_data[CONF_OWNER_ADDRESS] = owner_address
            storage_data[CONF_OWNER_SEED] = owner_seed
            await async_save_to_store(self.hass, STORAGE_ACCOUNT_SEED, storage_data)
        self.user_data[CONF_CONTROLLER_SEED] = controller_seed
        self.user_data[CONF_OWNER_ADDRESS] = owner_address
        self.user_data[CONF_OWNER_SEED] = owner_seed
        _LOGGER.debug(f"Finished configuration. Owner address: {owner_address}, controller_address: {get_address_for_seed(controller_seed)}")

