import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import ServiceCall, HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_CONTROLLER_SEED,
    CONF_EMAIL,
    CONF_OWNER_ADDRESS,
    DOMAIN,
    ROOT_LOGGER,
    LOGGER_HANDLER,
    PROBLEM_REPORT_SERVICE,
    CONF_OWNER_SEED,
    STORAGE_PINATA_CREDS,
    CONF_PINATA_PUBLIC,
    CONF_PINATA_SECRET,
    ROBONOMICS,
    RWS_CHECK_UNSUB,
    CHECK_ENTITIES_TRACK_TIME_UNSUB,
    HANDLE_CHECK_ENTITIES_TIME_CHANGE,
    CHECK_ENTITIES_TIMEOUT,
)
from .frontend import async_register_frontend, async_remove_frontend
from .robonomics import Robonomics
from .utils import (
    create_notification,
    async_load_from_store,
    async_remove_store,
    ReportServiceStatus,
    set_service_status,
    create_link_for_notification,
)
from .service import send_problem_report
from .libp2p import get_pinata_creds
from .websocket import async_register_websocket_commands
from .ipfs import pinata_creds_exists
from .entities_check import EntitiesStatusChecker
from .logger_handler import LoggerHandler
from .message_formatter import MessageFormatter

_LOGGER = logging.getLogger(__name__)


async def wait_for_pinata_creds(hass: HomeAssistant, entry: ConfigEntry):
    if not await pinata_creds_exists(hass):
        _LOGGER.debug("Pinata credentials are not in storage")
        while not await get_pinata_creds(
            hass,
            entry.data[CONF_CONTROLLER_SEED],
            entry.data[CONF_EMAIL],
            entry.data[CONF_OWNER_ADDRESS],
        ):
            await asyncio.sleep(0.5)
    else:
        _LOGGER.debug("Pinata credentials are in storage")
    await hass.data[DOMAIN][ROBONOMICS].async_init()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    set_service_status(hass, ReportServiceStatus.WaitPinataCreds)
    hass.data[DOMAIN][ROBONOMICS] = Robonomics(
        hass,
        entry.data[CONF_CONTROLLER_SEED],
        entry.data[CONF_OWNER_ADDRESS],
        entry.data.get(CONF_OWNER_SEED),
    )
    LoggerHandler().setup(hass)
    async_register_websocket_commands(hass)
    async_register_frontend(hass)

    async def check_rws_active(data=None):
        if ROBONOMICS in hass.data[DOMAIN]:
            if not await hass.data[DOMAIN][
                ROBONOMICS
            ].get_rws_left_days() or not await pinata_creds_exists(hass):
                # Delete pinata creds
                await async_remove_store(hass, STORAGE_PINATA_CREDS)
                entry.async_create_task(hass, wait_for_pinata_creds(hass, entry))

    async def handle_problem_report(call: ServiceCall) -> None:
        storage_data = await async_load_from_store(hass, STORAGE_PINATA_CREDS)
        if (
            CONF_PINATA_PUBLIC in storage_data
            and CONF_PINATA_SECRET in storage_data
            and ROBONOMICS in hass.data[DOMAIN]
        ):
            await send_problem_report(
                hass, call, hass.data[DOMAIN][ROBONOMICS], storage_data
            )

    await check_rws_active()
    hass.services.async_register(DOMAIN, PROBLEM_REPORT_SERVICE, handle_problem_report)
    # entry.async_create_task(hass, wait_for_pinata_creds(hass, entry))
    hass.data[DOMAIN][RWS_CHECK_UNSUB] = async_track_time_interval(
        hass,
        check_rws_active,
        timedelta(days=1),
    )
    async def check_states(_ = None):
        await asyncio.sleep(15)
        entities_checker = EntitiesStatusChecker(hass)
        unavailables = entities_checker.get_unavailables()
        not_updated = await entities_checker.get_not_updated()
        unavailables_text = MessageFormatter.format_devices_list(unavailables, "Found some unavailable devices:")
        not_updated_text = MessageFormatter.format_devices_list(not_updated, "Found some not updated for a long time devices:")
        problem_text = MessageFormatter.concatinate_messages(unavailables_text, not_updated_text)
        link = create_link_for_notification(problem_text)
        service_data = {
            "message": f"Found some unavaileble or not updated for a long time devices. [Click]({link})",
            "title": "Send Report Service",
        }
        await create_notification(hass, service_data)
    hass.data[DOMAIN][HANDLE_CHECK_ENTITIES_TIME_CHANGE] = check_states
    asyncio.ensure_future(check_states())
    hass.data[DOMAIN][CHECK_ENTITIES_TRACK_TIME_UNSUB] = async_track_time_interval(
        hass,
        hass.data[DOMAIN][HANDLE_CHECK_ENTITIES_TIME_CHANGE],
        timedelta(seconds=CHECK_ENTITIES_TIMEOUT),
    )

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
    hass.data[DOMAIN][ROOT_LOGGER].removeHandler(hass.data[DOMAIN][LOGGER_HANDLER])
    hass.data[DOMAIN][CHECK_ENTITIES_TRACK_TIME_UNSUB]()
    async_remove_frontend(hass)
    hass.data[DOMAIN][RWS_CHECK_UNSUB]()
    return True
