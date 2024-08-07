import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_SENDER_SEED,
    DOMAIN,
    ERROR_SOURCES_MANAGER,
    CONF_EMAIL
)
# from .frontend import async_register_frontend, async_remove_frontend
from .rws_registration import RWSRegistrationManager
from .robonomics import Robonomics
from .error_sources.error_source_manager import ErrorSourcesManager
from .report_service import ReportService

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][CONF_EMAIL] = entry.data[CONF_EMAIL]
    robonomics = Robonomics(
        hass,
        entry.data[CONF_SENDER_SEED],
    )
    # async_register_frontend(hass)
    await RWSRegistrationManager.register(hass, robonomics, entry.data[CONF_EMAIL])
    ReportService(hass, robonomics).register()
    error_sources_manager = ErrorSourcesManager(hass)
    error_sources_manager.setup_sources()
    hass.data[DOMAIN][ERROR_SOURCES_MANAGER] = error_sources_manager

    return True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.
    It calls during integration's removing.

    :param hass: HomeAssistant instance
    :param entry: Data from config

    :return: True if all unload event were success
    """
    hass.data[DOMAIN][ERROR_SOURCES_MANAGER].remove_sources()
    await RWSRegistrationManager.delete(hass)
    # async_remove_frontend(hass)
    return True
