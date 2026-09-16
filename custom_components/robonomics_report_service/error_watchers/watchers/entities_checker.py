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
from homeassistant.helpers.event import async_track_time_interval

from ...const import CHECK_ENTITIES_TIMEOUT
from .error_watcher import ErrorWatcher

_LOGGER = logging.getLogger(__name__)


class EntitiesStatusChecker(ErrorWatcher):
    """Periodic health-check for all entities (unavailable / not updated)"""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass)

        self.entity_registry = async_get_entity_registry(hass)
        self.devices_registry = async_get_devices_registry(hass)

        self._check_entities_timer_listener = None

        self._period_start = dt_util.utcnow()
        self._first_run = True

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
        # Start checking immediately
        self.hass.async_create_task(self._check_entities())

    @callback
    def remove(self) -> None:
        if self._check_entities_timer_listener is not None:
            self._check_entities_timer_listener()
            self._check_entities_timer_listener = None

        _LOGGER.debug("EntitiesStatusChecker removed")

    async def _check_entities(self, _=None) -> None:

        async with self._lock:
            # Delay to wait for the entities for the first run
            if self._first_run:
                await asyncio.sleep(15)
                self._first_run = False

            period_end = dt_util.utcnow()
            period_start = self._period_start

            all_entity_ids = self._get_all_entity_ids()

            unavailable_ids: list[str] = []

            for entity_id in all_entity_ids:
                entity_entry = self.entity_registry.async_get(entity_id)

                # Entities that have been explicitly disabled are
                # not considered problematic
                if entity_entry is not None and entity_entry.disabled:
                    continue

                entity_state = self.hass.states.get(entity_id)

                # Entity is unavaliable if explicit STATE_UNAVAILABLE
                if (
                    entity_state is not None
                    and entity_state.state == STATE_UNAVAILABLE
                ):
                    unavailable_ids.append(entity_id)
                    continue

            # If nothing to report, skip
            if not unavailable_ids:
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
                "summary": (
                    "Entities health: "
                    f"{unavailable_counts['entities']} unavailable "
                    f"({unavailable_counts['devices']} devices) "
                    f"(interval {CHECK_ENTITIES_TIMEOUT} min)"
                ),
                "details": {
                    "check_timeout_minutes": CHECK_ENTITIES_TIMEOUT,
                    "counts": {
                        "unavailable_counts": unavailable_counts,
                    },
                    "unavailable_entities": unavailable_entities,
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
