import typing as tp
import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.event import async_call_later
from homeassistant.data_entry_flow import FlowResult
from robonomicsinterface import Account

from .const import (
    DOMAIN,
    CONF_EMAIL,
    CONF_OWNER_SEED,
    PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
    CONF_PINATA_SECRET,
    CONF_PINATA_PUBLIC,
    STORAGE_ACCOUNT_SEED,
    CONF_OWNER_ADDRESS,
    CONF_CONTROLLER_SEED,
)
from .utils import encrypt_message, async_load_from_store, async_save_to_store
from .libp2p import get_pinata_creds
from .robonomics import create_account

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
        return await self.async_step_wait()

    async def async_step_wait(self, user_input: tp.Optional[dict] = None) -> FlowResult:
        async def _wait_for_payment(_=None):
            storage_data = await async_load_from_store(self.hass, STORAGE_ACCOUNT_SEED)
            # If Robonomics integration was configured, there will be controller seed and owner address in the storage
            if (
                CONF_CONTROLLER_SEED in storage_data
                and CONF_OWNER_ADDRESS in storage_data
            ):
                controller_seed = storage_data[CONF_CONTROLLER_SEED]
                controller_account = Account(controller_seed)
                owner_address = storage_data[CONF_OWNER_ADDRESS]
                owner_seed = None
            else:
                controller_seed, controller_account = create_account()
                owner_seed, owner_account = create_account()
                owner_address = owner_account.get_address()
                storage_data[CONF_CONTROLLER_SEED] = controller_seed
                storage_data[CONF_OWNER_ADDRESS] = owner_address
                await async_save_to_store(self.hass, STORAGE_ACCOUNT_SEED, storage_data)
            encrypted_email = encrypt_message(
                self.user_data["email"],
                sender_keypair=controller_account.keypair,
                recipient_address=PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
            )
            pinata_creds = await get_pinata_creds(
                controller_account.get_address(), encrypted_email, owner_address
            )
            self.paid = True
            self.user_data[CONF_CONTROLLER_SEED] = controller_seed
            self.user_data[CONF_OWNER_ADDRESS] = owner_address
            self.user_data[CONF_OWNER_SEED] = owner_seed
            self.user_data[CONF_PINATA_SECRET] = pinata_creds["secret"]
            self.user_data[CONF_PINATA_PUBLIC] = pinata_creds["public"]
            self.hass.async_create_task(
                self.hass.config_entries.flow.async_configure(flow_id=self.flow_id)
            )

        if not self.paid:
            async_call_later(self.hass, 1, _wait_for_payment)
            return self.async_show_progress(
                step_id="wait",
                progress_action="wait_for_payment",
            )

        return self.async_show_progress_done(next_step_id="device_done")

    async def async_step_device_done(self, user_input: tp.Optional[dict] = None):
        return self.async_create_entry(
            title="Robonomics Report Service", data=self.user_data
        )
