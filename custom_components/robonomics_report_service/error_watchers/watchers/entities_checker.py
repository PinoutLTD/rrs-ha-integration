import asyncio
import logging
from datetime import timedelta
from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.const import (
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.device_registry import (
    async_get as async_get_devices_registry,
)
from homeassistant.helpers.entity_registry import (
    async_get as async_get_entity_registry,
)
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.start import async_at_started

from ... import entity_health
from ...const import CHECK_ENTITIES_TIMEOUT, FIRST_ENTITIES_CHECK_DELAY
from .error_watcher import ErrorWatcher

_LOGGER = logging.getLogger(__name__)


class EntitiesStatusChecker(ErrorWatcher):
    """Periodic health-check for all entities (unavailable / not updated)"""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass)

        self.entity_registry = async_get_entity_registry(hass)
        self.devices_registry = async_get_devices_registry(hass)

        self._check_entities_timer_listener = None
        self._at_started_listener = None
        self._first_check_listener = None

        self._period_start = dt_util.utcnow()

        # Locker to prevent parallel checking
        self._lock = asyncio.Lock()

    @callback
    def setup(self) -> None:
        _LOGGER.debug("EntitiesStatusChecker start initializing")

        # Create timer to check entities and then call send_report service
        self._check_entities_timer_listener = async_track_time_interval(
            self.hass,
            self._check_entities,
            timedelta(minutes=CHECK_ENTITIES_TIMEOUT),
        )
        # The first check waits for Home Assistant to finish starting and then
        # a little longer: entities are set up and leave "unavailable" only
        # then, and a snapshot taken earlier reports half the house.
        self._at_started_listener = async_at_started(self.hass, self._schedule_first_check)

    @callback
    def _schedule_first_check(self, _hass: HomeAssistant) -> None:
        self._first_check_listener = async_call_later(
            self.hass, FIRST_ENTITIES_CHECK_DELAY, self._first_check
        )

    async def _first_check(self, _now=None) -> None:
        self._first_check_listener = None
        await self._check_entities()

    @callback
    def remove(self) -> None:
        if self._check_entities_timer_listener is not None:
            self._check_entities_timer_listener()
            self._check_entities_timer_listener = None
        for listener in (self._at_started_listener, self._first_check_listener):
            if listener is not None:
                listener()
        self._at_started_listener = None
        self._first_check_listener = None

        _LOGGER.debug("EntitiesStatusChecker removed")

    async def _check_entities(self, _=None) -> None:

        async with self._lock:
            period_end = dt_util.utcnow()
            period_start = self._period_start

            all_entity_ids = self._get_all_entity_ids()

            unavailable_ids: list[str] = []
            unavailable_by_entry: dict[str, int] = {}
            device_states: dict[str, entity_health.DeviceStates] = {}

            for entity_id in all_entity_ids:
                entity_entry = self.entity_registry.async_get(entity_id)

                # Entities that have been explicitly disabled are
                # not considered problematic
                if entity_entry is not None and entity_entry.disabled:
                    continue

                entity_state = self.hass.states.get(entity_id)
                if entity_state is None:
                    continue

                # A device's entities, to find devices that never delivered data
                if entity_entry is not None and entity_entry.device_id is not None:
                    device = device_states.get(entity_entry.device_id)
                    if device is None:
                        device = device_states[entity_entry.device_id] = (
                            entity_health.DeviceStates(
                                self._get_device_name(
                                    self.devices_registry.async_get(
                                        entity_entry.device_id
                                    )
                                )
                            )
                        )
                    device.states[entity_id] = entity_state.state

                # Entity is unavaliable if explicit STATE_UNAVAILABLE
                if entity_state.state == STATE_UNAVAILABLE:
                    unavailable_ids.append(entity_id)
                    if entity_entry is not None and entity_entry.config_entry_id:
                        entry_id = entity_entry.config_entry_id
                        unavailable_by_entry[entry_id] = (
                            unavailable_by_entry.get(entry_id, 0) + 1
                        )

            not_loaded = entity_health.not_loaded(
                self._entries(), unavailable_by_entry
            )
            silent = entity_health.silent_devices(device_states)

            # If nothing to report, skip
            if not unavailable_ids and not not_loaded and not silent:
                self._period_start = period_end
                return

            # Check if entities is part of some device
            unavailable_entities = self._group_by_device(unavailable_ids)

            unavailable_counts = self._count_devices_entities(
                unavailable_entities
            )
            email = await self._get_email()
            # Gather issue
            issue: dict[str, Any] = {
                "type": "entities_health_problems",
                "email": email,
                "schema_version": 1,
                "ts_start": period_start.isoformat(),
                "ts_end": period_end.isoformat(),
                "summary": entity_health.summary(
                    unavailable_counts["entities"],
                    unavailable_counts["devices"],
                    CHECK_ENTITIES_TIMEOUT,
                    len(not_loaded),
                    len(silent),
                ),
                "details": {
                    "check_timeout_minutes": CHECK_ENTITIES_TIMEOUT,
                    "counts": {
                        "unavailable_counts": unavailable_counts,
                    },
                    "unavailable_entities": unavailable_entities,
                    # Integrations not running, and devices that never
                    # delivered data (entity_health.py).
                    "integrations_not_loaded": not_loaded,
                    "devices_without_data": silent,
                    "preview": {
                        "unavailable_entities": self._preview_devices(
                            unavailable_entities
                        ),
                    },
                },
            }

            self._period_start = period_end

            _LOGGER.debug(
                "EntitiesStatusChecker sending report "
                "(unavailable_entities=%d, devices=%d)",
                unavailable_counts["entities"],
                unavailable_counts["devices"],
            )
            await self._send_report(issue)

    def _entries(self) -> list[entity_health.EntryInfo]:
        return [
            entity_health.EntryInfo(
                entry_id=entry.entry_id,
                domain=entry.domain,
                title=entry.title,
                state=entry.state.value,
                reason=entry.reason,
                disabled=entry.disabled_by is not None,
            )
            for entry in self.hass.config_entries.async_entries()
        ]

    def _get_all_entity_ids(self) -> set[str]:

        # Entities currently exist in the state machine
        live_entities = {
            state.entity_id for state in self.hass.states.async_all()
        }

        # Entities from the entity registry
        registered_entities = set(self.entity_registry.entities)

        # Return the union of both, since the first ones may not have
        # a unique ID, and the second ones may not have a state right now
        return live_entities | registered_entities

    def _group_by_device(self, entity_ids: list[str]) -> dict[str, Any]:

        result_dict: dict[str, Any] = {"devices": {}, "pure_entities": []}

        for entity_id in entity_ids:
            entity_entry = self.entity_registry.async_get(entity_id)

            # Entities without device
            if entity_entry is None or entity_entry.device_id is None:
                result_dict["pure_entities"].append(entity_id)
                continue

            device_id = entity_entry.device_id
            device = self.devices_registry.async_get(device_id)
            device_name = self._get_device_name(device)

            # Return an existing device entry in dict
            # or create a new one otherwise
            devices_in_dict = result_dict["devices"].setdefault(
                device_id,
                {"device_name": device_name, "entities": []},
            )

            devices_in_dict["entities"].append(entity_id)

        return result_dict

    @staticmethod
    def _get_device_name(device: DeviceEntry | None) -> str:
        if device is None:
            return "Unknown device"

        return (
            str(device.name_by_user)
            if device.name_by_user is not None
            else str(device.name)
        )

    @staticmethod
    def _count_devices_entities(data: dict) -> dict[str, int]:
        devices: dict = data.get("devices", {}) or {}
        pure_entities: list[str] = data.get("pure_entities", []) or []

        number_entities_in_devices = sum(
            len(v.get("entities") or []) for v in devices.values()
        )

        return {
            "devices": len(devices),
            "entities": number_entities_in_devices + len(pure_entities),
        }

    @staticmethod
    def _preview_devices(
        data: dict,
        max_devices: int = 20,
        max_entities_per_device: int = 20,
        max_pure_entities: int = 40,
    ) -> dict[str, Any]:

        devices: dict = data.get("devices", {}) or {}
        pure_entities: list[str] = data.get("pure_entities", []) or []

        device_items = list(devices.items())[:max_devices]
        devices_preview: dict[str, dict] = {}

        for device_id, info in device_items:
            entities_full = info.get("entities", []) or []
            entities = entities_full[:max_entities_per_device]

            devices_preview[device_id] = {
                "device_name": info.get("device_name"),
                "entities": entities,
            }

        pure_entities_preview = pure_entities[:max_pure_entities]

        return {
            "devices": devices_preview,
            "pure_entities": pure_entities_preview,
        }
