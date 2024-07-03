import typing as tp
from datetime import timedelta, datetime
import logging
import asyncio

from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.device_registry import async_get as async_get_devices_registry
from homeassistant.helpers.entity_registry import RegistryEntry
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.components.recorder import get_instance, history
import homeassistant.util.dt as dt_util
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers.event import async_track_time_interval

from .error_source import ErrorSource
from .utils.message_formatter import MessageFormatter
from ...const import CHECK_ENTITIES_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class EntitiesStatusChecker(ErrorSource):
    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass)
        self.entity_registry = async_get_entity_registry(hass)
        self.devices_registry = async_get_devices_registry(hass)
        self.unsub_timer = None

    @callback
    def setup(self) -> None:
        self.unsub_timer = async_track_time_interval(
            self.hass,
            self._check_entities,
            timedelta(hours=CHECK_ENTITIES_TIMEOUT),
        )
        asyncio.ensure_future(self._check_entities())

    @callback
    def remove(self) -> None:
        self.unsub_timer()

    async def _check_entities(self, _ = None):
        await asyncio.sleep(15)
        unavailables = self._get_unavailables()
        not_updated = await self._get_not_updated()
        unavailables_text = MessageFormatter.format_devices_list(unavailables, "unavailables")
        not_updated_text = MessageFormatter.format_devices_list(not_updated, "not updated")
        problem_text = MessageFormatter.concatinate_messages(unavailables_text, not_updated_text)
        await self._run_report_service(problem_text, "unresponded_devices")

    def _get_unavailables(self) -> tp.Dict:
        unavailables = []
        for entity in self.entity_registry.entities:
            entity_data = self.entity_registry.async_get(entity)
            if not self._is_available(entity) and not entity_data.disabled:
                unavailables.append(entity_data.entity_id)
        return self._get_dict_with_devices(unavailables)

    async def _get_not_updated(self) -> tp.Dict:
        not_updated = []
        for entity in self.entity_registry.entities:
            entity_data = self.entity_registry.async_get(entity)
            if not self._is_available(entity) or entity_data.disabled:
                continue
            if entity_data.entity_id.split(".")[0] == "sensor":
                if not await self._check_state_changed_during_period(entity_data.entity_id):
                    not_updated.append(entity_data.entity_id)
        return self._get_dict_with_devices(not_updated)
    
    def _get_dict_with_devices(self, entities_list: tp.List[str]) -> tp.Dict:
        res_dict = {"devices": {}, "entities": []}
        for entity_id in entities_list:
            entity_data = self.entity_registry.async_get(entity_id)
            if entity_data.device_id is not None:
                device = self.devices_registry.async_get(entity_data.device_id)
                if entity_data.device_id in res_dict["devices"]:
                    res_dict["devices"][entity_data.device_id]["entities"].append(entity_id)
                else:
                    res_dict["devices"][entity_data.device_id] = {"device_name": self._get_device_name(device), "entities": [entity_id]}
            else:
                res_dict["entities"].append(entity_id)
        return res_dict

    def _get_device_name(self, device: DeviceEntry) -> str:
        device_name = (
            str(device.name_by_user)
            if device.name_by_user != None
            else str(device.name)
        )
        return device_name

    def _is_available(self, entity: RegistryEntry):
        entity_state = self.hass.states.get(entity)
        if entity_state is not None:
            return entity_state.state != STATE_UNAVAILABLE
            

    async def _check_state_changed_during_period(self, entity_id: str, hours: int = 26) -> bool:
        start = dt_util.utcnow() - timedelta(hours=hours)
        end = dt_util.utcnow()
        instance = get_instance(self.hass)
        states = await instance.async_add_executor_job(
            self._state_changes_during_period,
            start,
            end,
            entity_id,
        )
        states = states[1:]
        if entity_id == "sensor.sun_next_noon":
            _LOGGER.debug(f"{entity_id} history: {states}")
        if len(states) > 0:
            last_state = states[-1].state
            for state in states:
                if state.state != STATE_UNAVAILABLE and state.state != STATE_UNKNOWN:
                    if state.state != last_state:
                        return True
            else:
                return False
        else:
            return False
    
    def _state_changes_during_period(
        self,
        start: datetime,
        end: datetime,
        entity_id: str,
    ) -> list[State]:
        return history.state_changes_during_period(
            self.hass,
            start,
            end,
            entity_id,
            include_start_time_state=True,
            no_attributes=True,
        ).get(entity_id, [])