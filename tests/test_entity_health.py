"""Integrations not loaded and devices without data, beside the unavailable list."""

from entity_health import DeviceStates, EntryInfo, not_loaded, silent_devices, summary


def entry(entry_id, domain, state, reason=None, disabled=False):
    return EntryInfo(entry_id, domain, domain.title(), state, reason, disabled)


def test_integrations_not_running_are_named_with_their_reason():
    entries = [
        entry("1", "xiaomi_miot", "setup_retry", "need_verify"),
        entry("2", "gree", "loaded"),
        entry("3", "inels", "setup_error", "No handler found"),
        entry("4", "old_thing", "setup_error", disabled=True),
        entry("5", "starting", "setup_in_progress"),
    ]

    found = not_loaded(entries, {"1": 22, "2": 5})

    assert [(e["domain"], e["state"], e["reason"], e["unavailable_entities"]) for e in found] == [
        ("xiaomi_miot", "setup_retry", "need_verify", 22),
        ("inels", "setup_error", "No handler found", 0),
    ]


def test_a_device_whose_every_entity_is_unknown_has_no_data():
    devices = {
        "board": DeviceStates(
            "BS_POE_ESP32C3",
            {"sensor.board_temperature": "unknown", "button.board_restart": "unknown"},
        ),
        "lamp": DeviceStates("Lamp", {"light.lamp": "on", "sensor.lamp_power": "unknown"}),
        "remote": DeviceStates(
            "Remote", {"button.remote_press": "unknown", "event.remote": "unknown"}
        ),
    }

    found = silent_devices(devices)

    # The lamp delivers data; the remote has only entities unknown by nature.
    assert found == {
        "board": {"device_name": "BS_POE_ESP32C3", "entities": ["sensor.board_temperature"]}
    }


def test_the_summary_keeps_its_old_start_and_adds_what_is_new():
    assert summary(82, 14, 1440, 0, 0) == (
        "Entities health: 82 unavailable (14 devices) (interval 1440 min)"
    )
    assert summary(82, 14, 1440, 1, 2) == (
        "Entities health: 82 unavailable (14 devices) (interval 1440 min); "
        "1 integration(s) not loaded; 2 device(s) without data"
    )
