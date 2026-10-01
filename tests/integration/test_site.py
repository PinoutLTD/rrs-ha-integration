"""The integration on a clean Home Assistant, from setup form to decrypted report."""

import logging
from datetime import timedelta

from homeassistant import config_entries
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from robonomicsinterface import Keypair

from custom_components.robonomics_report_service import host_health
from custom_components.robonomics_report_service.const import (
    CHECK_ENTITIES_TIMEOUT,
    CHECK_LOGS_TIMEOUT,
    DOMAIN,
    FIRST_ENTITIES_CHECK_DELAY,
    HEARTBEAT_STARTUP_DELAY,
    PROBLEM_REPORT_SERVICE,
)
from custom_components.robonomics_report_service.error_watchers.watchers import (
    host_health_watcher,
)

from ..conftest import SENDER_SEED
from .conftest import FakeChain, FakePinata, install, open_report

SITE = Keypair.from_secret(SENDER_SEED).address


async def advance(hass: HomeAssistant, freezer, delta: timedelta) -> None:
    """Move the clock, and let the timers that became due fire."""

    freezer.tick(delta)
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def settle(hass: HomeAssistant) -> None:
    """Let background work (the publishing queue, report tasks) finish."""

    for _ in range(3):
        await hass.async_block_till_done(wait_background_tasks=True)


async def test_setup_form_installs_and_the_site_says_it_is_alive(
    hass: HomeAssistant, chain: FakeChain, pinata: FakePinata, freezer
):
    entry = await install(hass)

    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert hass.services.has_service(DOMAIN, PROBLEM_REPORT_SERVICE)

    await advance(hass, freezer, timedelta(minutes=HEARTBEAT_STARTUP_DELAY + 1))
    await settle(hass)

    [beat] = chain.heartbeats()
    assert beat["v"] == "1.1.0-beta.7"
    assert beat["ha"]
    # Published by the site's own key, through its own subscription.
    assert chain.records[0][0] == SITE and chain.records[0][2] == SITE

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_only_one_installation(hass: HomeAssistant, installed):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.ABORT


async def test_wrong_pinata_keys_are_caught_by_the_form(
    hass: HomeAssistant, installed, aioclient_mock
):
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        "https://api.pinata.cloud/data/testAuthentication", status=401, json={}
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": installed.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "problem_service_robonomics_address": SITE,
            "pinata_public": "wrong",
            "pinata_secret": "wrong",
        },
    )

    assert result["errors"] == {"base": "invalid_pinata_keys"}


async def test_a_report_on_demand_arrives_encrypted_for_the_integrator(
    hass: HomeAssistant, installed, chain: FakeChain, pinata: FakePinata
):
    issue = {"type": "installation_check", "summary": "test report from the harness"}

    await hass.services.async_call(DOMAIN, PROBLEM_REPORT_SERVICE, issue, blocking=True)
    await settle(hass)

    [cid] = chain.report_cids()
    report = open_report(pinata, cid)
    assert report.issue == issue


async def test_unavailable_entities_are_reported_after_start(
    hass: HomeAssistant, chain: FakeChain, pinata: FakePinata, freezer
):
    hass.states.async_set("sensor.harness_probe", STATE_UNAVAILABLE)

    entry = await install(hass)
    await settle(hass)
    # Not at once: the first check waits for entities to settle after start.
    assert chain.report_cids() == []

    await advance(hass, freezer, timedelta(seconds=FIRST_ENTITIES_CHECK_DELAY + 1))
    await settle(hass)

    [cid] = chain.report_cids()
    issue = open_report(pinata, cid).issue
    assert issue["type"] == "entities_health_problems"
    assert "sensor.harness_probe" in issue["details"]["unavailable_entities"]["pure_entities"]
    assert issue["details"]["check_timeout_minutes"] == CHECK_ENTITIES_TIMEOUT

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_errors_in_the_log_are_reported_once_a_day(
    hass: HomeAssistant, installed, chain: FakeChain, pinata: FakePinata, freezer
):
    logging.getLogger("custom_components.harness_probe").error("Probe failure number %s", 7)
    await hass.async_block_till_done()

    await advance(hass, freezer, timedelta(minutes=CHECK_LOGS_TIMEOUT + 1))
    await settle(hass)

    issues = [open_report(pinata, cid).issue for cid in chain.report_cids()]
    logs = [i for i in issues if i and i["type"] == "accumulated_system_log_problems"]
    assert len(logs) == 1
    assert "Probe failure" in str(logs[0]["details"])


async def test_host_memory_above_the_limit_is_reported_once(
    hass: HomeAssistant, installed, chain: FakeChain, pinata: FakePinata, monkeypatch, freezer
):
    total_kib = 4 * 1024 * 1024
    meminfo = (
        f"MemTotal: {total_kib} kB\nMemAvailable: {total_kib // 20} kB\n"
        f"SwapTotal: {total_kib // 2} kB\nSwapFree: {total_kib // 4} kB\n"
    )
    monkeypatch.setattr(host_health_watcher, "_read_meminfo", lambda: meminfo)

    for _ in range(6):
        await advance(hass, freezer, host_health.SAMPLE_INTERVAL)
    await settle(hass)

    issues = [open_report(pinata, cid).issue for cid in chain.report_cids()]
    health = [i for i in issues if i and i["type"] == "host_health"]
    assert len(health) == 1
    assert health[0]["summary"] == "Host health: memory above 90% for 30 min (peak 95%)"
    assert health[0]["details"]["memory"]["swap_used_mib"] == 1024


async def test_removing_the_integration_leaves_nothing_behind(
    hass: HomeAssistant, installed, hass_storage
):
    assert "robonomics_report_service.creds_storage" in hass_storage

    assert await hass.config_entries.async_remove(installed.entry_id)
    await hass.async_block_till_done()

    left = [key for key in hass_storage if key.startswith(DOMAIN)]
    assert left == []
    assert not hass.services.has_service(DOMAIN, PROBLEM_REPORT_SERVICE)


async def test_an_unclean_shutdown_before_this_start_is_reported(
    hass: HomeAssistant, chain: FakeChain, pinata: FakePinata
):
    from homeassistant.components.recorder.db_schema import Events, RecorderRuns
    from homeassistant.helpers.recorder import get_instance, session_scope

    instance = get_instance(hass)
    started = instance.recorder_runs_manager.recording_start
    last_seen = started - timedelta(hours=9, minutes=34)

    def leave_a_frozen_run():
        # What the recorder finds after a freeze: the old run ended at this
        # start and marked incorrect, its last event hours before.
        with session_scope(hass=hass) as session:
            session.add(
                RecorderRuns(
                    start=started - timedelta(days=8),
                    end=started,
                    closed_incorrect=True,
                    created=started - timedelta(days=8),
                )
            )
            session.add(Events(time_fired_ts=last_seen.timestamp()))

    await instance.async_add_executor_job(leave_a_frozen_run)

    entry = await install(hass)
    await settle(hass)

    issues = [open_report(pinata, cid).issue for cid in chain.report_cids()]
    [health] = [i for i in issues if i and i["type"] == "host_health"]
    assert health["summary"] == (
        "Host health: Home Assistant was down 9 h 34 min, shutdown not clean"
    )
    assert health["details"]["shutdown"]["last_seen"] == last_seen.isoformat()

    # Reloading the integration does not report the same shutdown again.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await settle(hass)
    issues = [open_report(pinata, cid).issue for cid in chain.report_cids()]
    assert len([i for i in issues if i and i["type"] == "host_health"]) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
