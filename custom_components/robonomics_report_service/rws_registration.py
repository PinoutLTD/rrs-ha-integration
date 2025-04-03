from homeassistant.core import HomeAssistant
import logging

from .robonomics import Robonomics
from .libp2p import LibP2P
from .utils import pinata_creds_exists, async_remove_store, async_save_to_store
from .const import (
    STORAGE_CREDENTIALS,
    CONF_PINATA_PUBLIC,
    CONF_PINATA_SECRET,
    DOMAIN,
    CONF_EMAIL,
    CONF_INTEGRATOR_ADDRESS,
)


_LOGGER = logging.getLogger(__name__)


class RWSRegistrationManager:

    @staticmethod
    async def register(
        hass: HomeAssistant, robonomics: Robonomics, libp2p: LibP2P, email: str = None
    ) -> None:
        if not await pinata_creds_exists(hass):
            integrator_address = await libp2p.get_integrator_address()
            robonomics.set_integrator_address(integrator_address)
            email = email if email else hass.data[DOMAIN][CONF_EMAIL]
            encrypted_email = robonomics.encrypt_for_integrator(email)
            resp = await libp2p.get_pinata_creds(encrypted_email)
            await RWSRegistrationManager._save_service_creds(hass, robonomics, resp)

    @staticmethod
    async def request_new_pinata_creds(
        hass: HomeAssistant, robonomics: Robonomics, libp2p: LibP2P
    ) -> None:
        _LOGGER.debug("Start requesting new Pinata credentials")
        encrypted_email = robonomics.encrypt_for_integrator(
            hass.data[DOMAIN][CONF_EMAIL]
        )
        resp = await libp2p.get_pinata_creds(encrypted_email)
        await RWSRegistrationManager._save_service_creds(hass, robonomics, resp)

    @staticmethod
    async def delete(hass: HomeAssistant) -> None:
        _LOGGER.debug("Remove credentials store")
        await async_remove_store(hass, STORAGE_CREDENTIALS)

    @staticmethod
    async def _save_service_creds(
        hass: HomeAssistant, robonomics: Robonomics, resp: dict
    ) -> None:
        storage_data = {}
        storage_data[CONF_PINATA_PUBLIC] = robonomics.decrypt_message(resp["public"])
        storage_data[CONF_PINATA_SECRET] = robonomics.decrypt_message(resp["private"])
        storage_data[CONF_INTEGRATOR_ADDRESS] = robonomics._integrator_address
        _LOGGER.debug(f"Save credentials: {storage_data}")
        await async_save_to_store(
            hass,
            STORAGE_CREDENTIALS,
            storage_data,
        )
