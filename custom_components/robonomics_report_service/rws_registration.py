from homeassistant.core import HomeAssistant
import logging

from .robonomics import Robonomics
from .libp2p import LibP2P
from .utils import pinata_creds_exists, async_remove_store
from .const import STORAGE_PINATA_CREDS

_LOGGER = logging.getLogger(__name__)

class RWSRegistrationManager:

    @staticmethod
    async def register(hass: HomeAssistant, robonomics: Robonomics, email: str) -> None:
        libp2p = LibP2P(hass, robonomics.sender_seed, email)
        if not await pinata_creds_exists(hass):
            await libp2p.get_and_save_pinata_creds()
        await robonomics.wait_for_rws()

    @staticmethod
    async def delete(hass: HomeAssistant) -> None:
        _LOGGER.debug("Remove pinata creds store")
        await async_remove_store(hass, STORAGE_PINATA_CREDS)
    