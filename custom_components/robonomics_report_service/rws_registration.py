from homeassistant.core import HomeAssistant

from .robonomics import Robonomics
from .libp2p import LibP2P
from .utils import pinata_creds_exists

class RWSRegistrationManager:
    def __init__(self, hass: HomeAssistant, robonomics: Robonomics, email: str) -> None:
        self.hass = hass
        self.robonomics = robonomics
        self.libp2p = LibP2P(hass, self.robonomics.sender_seed, email)

    async def register(self) -> None:
        if not await pinata_creds_exists(self.hass):
            await self.libp2p.get_and_save_pinata_creds()
        await self.robonomics.wait_for_rws()
    