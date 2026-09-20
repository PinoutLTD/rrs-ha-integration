"""The heartbeat's own rules, without Home Assistant's scheduler."""

import json
from datetime import UTC, datetime, timedelta

import pytest

heartbeat = pytest.importorskip(
    "custom_components.robonomics_report_service.heartbeat",
    reason="the heartbeat module schedules through Home Assistant",
)

DAY = timedelta(days=1)
# Accounts of the published test mnemonics in tests/fixtures, not real sites.
SITE = "4GEGoUCyDw2FhnFtniYfo1xTqxBUhKZYRWkWyJ8BamqadVxp"
OTHER = "4DNteL1am4a3JBt2XE4cwrZ4YYxQztjMFUUdkrv24EgSvXfz"
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def test_payload_says_only_that_the_site_is_alive():
    payload = heartbeat.heartbeat_payload("1.1.0-beta.4", "2026.7.0", NOW)

    assert payload == {"t": "hb", "v": "1.1.0-beta.4", "ha": "2026.7.0", "ts": 1789905600}
    # It travels in the datalog itself, so its size is the cost of sending it.
    assert len(json.dumps(payload, separators=(",", ":"))) < 120


def test_sites_are_spread_across_the_interval_by_their_address():
    mine, other = heartbeat.send_offset(SITE, DAY), heartbeat.send_offset(OTHER, DAY)

    assert mine != other
    assert timedelta(0) <= mine < DAY and timedelta(0) <= other < DAY
    assert heartbeat.send_offset(SITE, DAY) == mine  # same site, same slot


def test_next_send_is_one_interval_apart_and_keeps_the_site_slot():
    first = heartbeat.next_send_time(SITE, DAY, NOW)
    second = heartbeat.next_send_time(SITE, DAY, first)

    assert first > NOW
    assert second - first == DAY
    assert (first - heartbeat.send_offset(SITE, DAY)).timestamp() % DAY.total_seconds() == 0


def test_a_restart_does_not_move_the_slot_or_add_a_beat():
    scheduled = heartbeat.next_send_time(SITE, DAY, NOW)
    restarted_later = heartbeat.next_send_time(SITE, DAY, NOW + timedelta(hours=3))

    assert restarted_later == scheduled


class FakeRobonomics:
    def __init__(self, fails: bool = False) -> None:
        self.sender_address = SITE
        self.sent: list[tuple[dict, bool]] = []
        self.fails = fails

    async def send_datalog(self, data, cleanup_pinata: bool = True) -> None:
        self.sent.append((data, cleanup_pinata))
        if self.fails:
            raise RuntimeError("no endpoint answered")


async def send_once(robonomics) -> None:
    beat = heartbeat.Heartbeat.__new__(heartbeat.Heartbeat)
    beat.robonomics = robonomics
    beat.version = "1.1.0-beta.4"
    await beat.send()


@pytest.mark.asyncio
async def test_heartbeat_is_not_a_report_so_nothing_is_unpinned():
    robonomics = FakeRobonomics()

    await send_once(robonomics)

    (payload, cleanup_pinata), = robonomics.sent
    assert payload["t"] == "hb"
    # A report's payload is a CID and is unpinned when sending fails; this
    # payload is JSON, and treating it as CIDs would unpin nonsense.
    assert cleanup_pinata is False


@pytest.mark.asyncio
async def test_a_missed_beat_is_logged_and_does_not_raise(caplog):
    await send_once(FakeRobonomics(fails=True))

    assert "Heartbeat was not sent" in caplog.text
