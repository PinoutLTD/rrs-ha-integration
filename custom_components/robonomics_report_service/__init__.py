import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import (
    CONF_NETWORK,
    CONF_SENDER_SEED,
    CREDS_STORAGE_KEY,
    DATALOG_QUEUE_STORAGE_KEY,
    DOMAIN,
    ERROR_WATCHERS_MANAGER,
    HEARTBEAT,
    HEARTBEAT_INTERVAL,
    HEARTBEAT_STARTUP_DELAY,
    LOGS_BACKUP_PATH,
    LOGS_PATH,
    OWNER_ADDRESS,
    PROBLEM_REPORT_SERVICE,
    PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
)
from .error_watchers.error_watchers_manager import ErrorWatchersManager
from .exceptions import StorageError
from .heartbeat import Heartbeat
from .ipfs import IPFS
from .report_service import ReportService
from .robonomics import Robonomics
from .utils.file_handler import remove_logs_dir_if_empty, remove_logs_files
from .utils.ha_storage import async_load_from_store, async_remove_store

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Setup of a specific integration instance.

    Called by the config entries manager if:
    - the user added the integration via the UI
    - HA restores existing entries upon startup
    """

    # Check that the global dict for integration exists
    hass.data.setdefault(DOMAIN, {})

    hass.data[DOMAIN].setdefault(entry.entry_id, {})

    try:
        # Load credentials from storage
        creds_storage = await async_load_from_store(hass, CREDS_STORAGE_KEY)

        # Prepare Robonomics and IPFS classes
        ipfs = IPFS(hass)
        robonomics = Robonomics(
            hass,
            creds_storage[CONF_NETWORK],
            ipfs,
            creds_storage[CONF_SENDER_SEED],
            creds_storage.get(OWNER_ADDRESS),
        )

        # Prepare report service
        report_service = ReportService(
            hass,
            ipfs,
            robonomics,
            creds_storage[PROBLEM_SERVICE_ROBONOMICS_ADDRESS],
        )
        await report_service.async_init()
        await robonomics.async_start()
    except (StorageError, KeyError) as e:
        _LOGGER.error(
            "Failed to set up %s: missing/invalid stored credentials: %s",
            DOMAIN,
            e,
        )
        return False

    except Exception:
        _LOGGER.exception(
            "Failed to set up %s due to unexpected error", DOMAIN
        )
        return False

    # Register send_report as HA service
    hass.data[DOMAIN][entry.entry_id]["report_service"] = report_service
    hass.data[DOMAIN][entry.entry_id]["robonomics"] = robonomics

    async def _handle_send_report(call: ServiceCall) -> None:
        # Allow calling the service from UI, just to send pure logs
        issue = dict(call.data) if call.data else None
        await report_service.send_report(issue=issue)

    hass.services.async_register(
        DOMAIN, PROBLEM_REPORT_SERVICE, _handle_send_report
    )

    # Say "the site is alive" once a day, so that silence means something.
    integration = await async_get_integration(hass, DOMAIN)
    heartbeat = Heartbeat(
        hass,
        robonomics,
        str(integration.version),
        timedelta(minutes=HEARTBEAT_INTERVAL),
        timedelta(minutes=HEARTBEAT_STARTUP_DELAY),
    )
    heartbeat.start()
    hass.data[DOMAIN][entry.entry_id][HEARTBEAT] = heartbeat

    # Configure and start manager for errors watchers
    error_watchers_manager = ErrorWatchersManager(hass)
    error_watchers_manager.setup_watchers()
    hass.data[DOMAIN][entry.entry_id][ERROR_WATCHERS_MANAGER] = (
        error_watchers_manager
    )

    return True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """
    Global integration setup.

    Called at HA startup when it loads the configuration.
    """
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Unload a config entry.
    """
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})

    heartbeat = data.get(HEARTBEAT)

    if heartbeat:
        heartbeat.stop()

    error_watchers_manager = data.get(ERROR_WATCHERS_MANAGER)

    if error_watchers_manager:
        try:
            error_watchers_manager.remove_watchers()
        except Exception:
            _LOGGER.debug("Failed to remove watchers", exc_info=True)

    hass.services.async_remove(DOMAIN, PROBLEM_REPORT_SERVICE)

    robonomics = data.get("robonomics")

    if robonomics:
        # The queue is saved as it changes; closing drops only the connection.
        await robonomics.async_close()

    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Called when the config entry is removed from Home Assistant."""
    await async_remove_store(hass, CREDS_STORAGE_KEY)
    await async_remove_store(hass, DATALOG_QUEUE_STORAGE_KEY)

    log_path = hass.config.path(LOGS_PATH)
    backup_path = hass.config.path(LOGS_BACKUP_PATH)

    try:
        await hass.async_add_executor_job(
            remove_logs_files, log_path, backup_path
        )
        await hass.async_add_executor_job(remove_logs_dir_if_empty, log_path)
    except Exception:
        _LOGGER.debug(
            "Failed to clean up integration log files", exc_info=True
        )
