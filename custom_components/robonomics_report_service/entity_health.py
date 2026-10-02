"""What the entities report says beyond "unavailable".

Two things a list of unavailable entities hides:

- **an integration that did not load.** Twenty unavailable entities of one
  vacuum read as twenty problems; they are one: its integration is waiting for
  a login (`setup_retry`, "need_verify"). The report names the integration,
  its state and Home Assistant's reason, with how many of the unavailable
  entities are its own;
- **a device that never delivers data.** An entity in `unknown` is not
  unavailable, so a board that announced itself over MQTT and then went
  silent dropped out of the report altogether (HT00010). A device whose every
  entity is `unknown` is listed. Entities that are `unknown` by nature —
  buttons, events, scenes — do not count, either way.

Nothing here imports Home Assistant: the watcher passes plain values in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Config entry states (homeassistant.config_entries.ConfigEntryState values)
# that mean the integration is not running when it should be.
NOT_LOADED_STATES = {"setup_error", "setup_retry", "migration_error", "failed_unload"}

# Domains whose entities are `unknown` until something happens, by design.
UNKNOWN_BY_NATURE = {
    "button",
    "event",
    "scene",
    "notify",
    "stt",
    "tts",
    "conversation",
    "wake_word",
    "assist_satellite",
    "image",
    "text",
}

STATE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class EntryInfo:
    entry_id: str
    domain: str
    title: str
    state: str
    reason: str | None
    disabled: bool


def not_loaded(entries: list[EntryInfo], unavailable_by_entry: dict[str, int]) -> list[dict]:
    """Enabled config entries that are not running, with their reason."""

    found = []
    for entry in entries:
        if entry.disabled or entry.state not in NOT_LOADED_STATES:
            continue
        found.append(
            {
                "domain": entry.domain,
                "title": entry.title,
                "state": entry.state,
                "reason": entry.reason,
                "unavailable_entities": unavailable_by_entry.get(entry.entry_id, 0),
            }
        )
    return sorted(found, key=lambda e: (-e["unavailable_entities"], e["domain"]))


@dataclass
class DeviceStates:
    name: str
    states: dict[str, str] = field(default_factory=dict)  # entity_id → state


def silent_devices(devices: dict[str, DeviceStates]) -> dict[str, dict]:
    """Devices whose every counted entity is `unknown`: no data ever arrived."""

    found = {}
    for device_id, device in devices.items():
        counted = {
            entity_id: state
            for entity_id, state in device.states.items()
            if entity_id.split(".", 1)[0] not in UNKNOWN_BY_NATURE
        }
        if counted and all(state == STATE_UNKNOWN for state in counted.values()):
            found[device_id] = {
                "device_name": device.name,
                "entities": sorted(counted),
            }
    return found


def summary(
    unavailable: int, devices: int, minutes: int, not_loaded_count: int, silent_count: int
) -> str:
    text = (
        f"Entities health: {unavailable} unavailable ({devices} devices) (interval {minutes} min)"
    )
    extra = []
    if not_loaded_count:
        extra.append(f"{not_loaded_count} integration(s) not loaded")
    if silent_count:
        extra.append(f"{silent_count} device(s) without data")
    return text + ("; " + "; ".join(extra) if extra else "")
