from typing import Any, cast

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.selector import selector

from .chain import Keypair, ss58_decode
from .const import (
    CONF_NETWORK,
    CONF_PINATA_PUBLIC,
    CONF_PINATA_SECRET,
    CONF_SENDER_EMAIL,
    CONF_SENDER_SEED,
    CREDS_STORAGE_KEY,
    DEFAULT_NETWORK,
    DOMAIN,
    NETWORK_KUSAMA,
    NETWORK_POLKADOT,
    OWNER_ADDRESS,
    PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
)
from .exceptions import StorageError
from .ipfs import async_check_pinata_keys
from .robonomics import Robonomics
from .utils.ha_storage import async_load_from_store, async_save_to_store

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NETWORK, default=DEFAULT_NETWORK): selector(
            {
                "select": {
                    "options": [
                        {"value": NETWORK_POLKADOT, "label": "Polkadot"},
                        {"value": NETWORK_KUSAMA, "label": "Kusama"},
                    ],
                    "mode": "dropdown",
                }
            }
        ),
        vol.Required(PROBLEM_SERVICE_ROBONOMICS_ADDRESS): str,
        vol.Required(CONF_PINATA_PUBLIC): str,
        vol.Required(CONF_PINATA_SECRET): str,
        vol.Optional(CONF_SENDER_EMAIL): str,
        vol.Optional(OWNER_ADDRESS): str,
    }
)

STEP_SEED_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_SENDER_SEED): str,
    }
)


def reconfigure_schema(current: dict[str, Any]) -> vol.Schema:
    """The editable settings, prefilled; secrets are asked for again."""

    return vol.Schema(
        {
            vol.Required(
                PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
                default=current.get(PROBLEM_SERVICE_ROBONOMICS_ADDRESS, ""),
            ): str,
            vol.Required(CONF_PINATA_PUBLIC, default=current.get(CONF_PINATA_PUBLIC, "")): str,
            vol.Required(CONF_PINATA_SECRET): str,
            vol.Optional(
                CONF_SENDER_EMAIL,
                description={"suggested_value": current.get(CONF_SENDER_EMAIL)},
            ): str,
            vol.Optional(
                OWNER_ADDRESS,
                description={"suggested_value": current.get(OWNER_ADDRESS)},
            ): str,
        }
    )


def address_errors(values: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    for field in (PROBLEM_SERVICE_ROBONOMICS_ADDRESS, OWNER_ADDRESS):
        address = (values.get(field) or "").strip()
        if not address:
            continue
        try:
            ss58_decode(address)
        except ValueError:
            errors[field] = "invalid_address"
    return errors


class ReportServiceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Handle a config flow for the Report Service during integration setup.

    The class object exists only for the duration of the setup wizard,
    and the result is a ConfigEntry that lives permanently.
    """

    # The schema version of the entries that it creates
    # HA will call migrate method if the version changes
    VERSION = 1

    def __init__(self):
        self._generated_seed: str | None = None
        self._generated_address: str | None = None
        self._storage_data = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The initial step of the configuration"""

        # Since it is needed exactly one integration instance, then assign
        # a unique ID to the flow and abort the flow if another flow
        # with the same unique ID is in progress
        await self.async_set_unique_id(DOMAIN)

        # Abort the flow if a config entry with the same unique ID exists
        self._abort_if_unique_id_configured()

        # Show the form to enter Pinata and Robonomics data
        # if it hasn't already been done, then save data in _storage_data
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA)
        self._storage_data.update(user_input)

        return await self.async_step_seed()

    async def async_step_seed(self, user_input=None) -> ConfigFlowResult:
        """Show the seed to user and configure Robonomics"""
        errors: dict[str, str] = {}

        # Generate seed/address once for fallback and UI preview
        if self._generated_seed is None:
            try:
                self._generated_seed = Robonomics.generate_seed()
                generated_kp = Keypair.create_from_secret(cast(str, self._generated_seed))
                self._generated_address = generated_kp.ss58_address
            except Exception:
                errors["base"] = "seed_generation_failed"

        if user_input is None or errors:
            return self.async_show_form(
                step_id="seed",
                data_schema=STEP_SEED_DATA_SCHEMA,
                description_placeholders={
                    "generated_seed": self._generated_seed or "",
                    "generated_address": self._generated_address or "",
                },
                errors=errors,
            )

        custom_seed = (user_input.get(CONF_SENDER_SEED) or "").strip()
        selected_seed = custom_seed or cast(str, self._generated_seed)

        try:
            # Validation only: a seed that cannot produce a keypair would
            # leave the site unable to publish anything.
            Keypair.create_from_secret(selected_seed)
        except Exception:
            return self.async_show_form(
                step_id="seed",
                data_schema=STEP_SEED_DATA_SCHEMA,
                description_placeholders={
                    "generated_seed": self._generated_seed or "",
                    "generated_address": self._generated_address or "",
                },
                errors={"base": "invalid_seed"},
            )

        self._storage_data[CONF_SENDER_SEED] = selected_seed

        # Save config to persistent storage without direct user access from UI
        try:
            await async_save_to_store(
                self.hass,
                CREDS_STORAGE_KEY,
                self._storage_data,
            )
        except StorageError:
            return self.async_show_form(
                step_id="seed",
                data_schema=STEP_SEED_DATA_SCHEMA,
                description_placeholders={
                    "generated_seed": self._generated_seed or "",
                    "generated_address": self._generated_address or "",
                },
                errors={"base": "storage_save_failed"},
            )

        # Make a mark in ConfigEntry that configuration is done
        return self.async_create_entry(
            title="Robonomics Report Service", data={"creds_configured": True}
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change keys and addresses without touching the seed.

        Removing the integration deletes its stored credentials, seed
        included, and the site would come back with a new address that is in
        no subscription. This step is the way to replace Pinata keys or point
        the site at another recipient or subscription owner instead.
        """

        current = await async_load_from_store(self.hass, CREDS_STORAGE_KEY)
        errors: dict[str, str] = {}

        if user_input is not None:
            values = {
                key: value.strip() if isinstance(value, str) else value
                for key, value in user_input.items()
            }
            errors = address_errors(values)
            if not errors:
                pinata_error = await async_check_pinata_keys(
                    self.hass, values[CONF_PINATA_PUBLIC], values[CONF_PINATA_SECRET]
                )
                if pinata_error:
                    errors["base"] = pinata_error

            if not errors:
                updated = dict(current)
                updated.update(values)
                # Empty optional fields mean "no longer set".
                for field in (CONF_SENDER_EMAIL, OWNER_ADDRESS):
                    if not values.get(field):
                        updated.pop(field, None)
                try:
                    await async_save_to_store(self.hass, CREDS_STORAGE_KEY, updated)
                except StorageError:
                    errors["base"] = "storage_save_failed"
                else:
                    return self.async_update_reload_and_abort(self._get_reconfigure_entry())

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=reconfigure_schema(current),
            errors=errors,
        )
