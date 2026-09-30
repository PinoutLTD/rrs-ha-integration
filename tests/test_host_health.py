"""Host health rules: when memory is worth a report, and how a report reads."""

from datetime import UTC, datetime, timedelta

import host_health
from host_health import MemorySample, MemoryWatch, parse_meminfo, shutdown_finding

GIB = 1024**3
T0 = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
STEP = host_health.SAMPLE_INTERVAL

MEMINFO = """\
MemTotal:        3884144 kB
MemFree:          112344 kB
MemAvailable:     194208 kB
Buffers:            1024 kB
SwapTotal:       2621436 kB
SwapFree:          62912 kB
"""


def at_percent(percent: float) -> MemorySample:
    total = 4 * GIB
    return MemorySample(
        total_bytes=total,
        available_bytes=int(total * (100 - percent) / 100),
        swap_total_bytes=2 * GIB,
        swap_free_bytes=GIB,
    )


def feed(watch: MemoryWatch, percents: list[float], start: datetime = T0) -> list[dict]:
    findings = []
    for i, percent in enumerate(percents):
        findings += watch.add(at_percent(percent), start + i * STEP)
    return findings


def test_meminfo_is_read_as_the_kernel_counts_it():
    sample = parse_meminfo(MEMINFO)

    assert sample is not None
    assert round(sample.used_percent) == 95
    assert host_health.mib(sample.swap_used_bytes) == 2499


def test_meminfo_without_available_memory_is_not_guessed():
    assert parse_meminfo("MemTotal: 1000 kB\nMemFree: 10 kB\n") is None
    assert parse_meminfo("") is None


def test_a_short_spike_is_not_reported():
    # Above the limit for 20 minutes, then back.
    assert feed(MemoryWatch(), [80, 95, 96, 97, 80]) == []


def test_memory_above_the_limit_for_half_an_hour_is_reported_once():
    findings = feed(MemoryWatch(), [80, 91, 93, 97, 94, 95, 96, 96, 95])

    assert [f["finding"] for f in findings] == ["memory"]
    memory = findings[0]
    assert memory["peak_percent"] == 97.0
    assert memory["peak_at"] == (T0 + 3 * STEP).isoformat()
    assert memory["above_since"] == (T0 + STEP).isoformat()
    assert memory["swap_used_mib"] == 1024


def test_hovering_at_the_limit_is_one_episode_until_memory_falls_well_below():
    watch = MemoryWatch()
    # 88% is under the limit but above the re-arm level: the episode goes on.
    percents = [95, 95, 95, 95, 88, 95, 95, 95, 95]
    assert len(feed(watch, percents)) == 1

    # Well below, then high again: a new episode, a new report.
    later = T0 + len(percents) * STEP
    assert len(feed(watch, [70, 95, 95, 95, 95], start=later)) == 1


def test_the_report_says_how_much_memory_grew_over_the_day():
    watch = MemoryWatch()
    feed(watch, [60], start=T0 - timedelta(hours=20))
    findings = feed(watch, [95, 95, 95, 95])

    assert findings[0]["change_percent"] == 35.0
    assert findings[0]["change_since"] == (T0 - timedelta(hours=20)).isoformat()


def daily(means: list[float], last_day: datetime) -> dict[str, list[float]]:
    days = {}
    for i, mean in enumerate(reversed(means)):
        day = (last_day - timedelta(days=i)).date().isoformat()
        days[day] = [mean * 10, 10]
    return days


def test_a_steady_climb_is_reported_before_the_limit():
    today = T0.date()
    watch = MemoryWatch(daily=daily([62, 68, 73, 79], T0 - timedelta(days=1)))

    growth = watch.growth(today)

    assert growth is not None
    assert list(growth["daily_mean_percent"].values()) == [62, 68, 73, 79]
    # The same climb is not reported twice, even a day later.
    assert watch.growth(today) is None
    watch.daily.update(daily([84], T0))
    assert watch.growth(today + timedelta(days=1)) is None


def test_settling_after_boot_or_a_dip_is_not_a_climb():
    yesterday = T0 - timedelta(days=1)
    # Rising but low: a system settling after boot.
    assert MemoryWatch(daily=daily([40, 45, 52, 60], yesterday)).growth(T0.date()) is None
    # High but one day went down.
    assert MemoryWatch(daily=daily([70, 78, 76, 85], yesterday)).growth(T0.date()) is None
    # Rising by less than the minimum.
    assert MemoryWatch(daily=daily([75, 76, 78, 80], yesterday)).growth(T0.date()) is None
    # A missing day breaks the run.
    days = daily([62, 68, 73, 79], yesterday)
    del days[(yesterday - timedelta(days=1)).date().isoformat()]
    assert MemoryWatch(daily=days).growth(T0.date()) is None


def test_old_days_are_pruned():
    watch = MemoryWatch(daily=daily([50] * 20, T0))
    watch.prune(T0.date())

    assert len(watch.daily) == host_health.DAYS_KEPT + 1


def test_a_clean_shutdown_is_not_reported():
    assert shutdown_finding(False, T0, T0 + timedelta(hours=9), None) is None


def test_an_unclean_shutdown_says_when_the_host_went_and_came_back():
    last_seen = datetime(2026, 9, 28, 19, 15, 54, tzinfo=UTC)
    started = datetime(2026, 9, 29, 4, 49, 30, tzinfo=UTC)
    booted = datetime(2026, 9, 29, 4, 48, tzinfo=UTC)

    finding = shutdown_finding(True, last_seen, started, booted)

    assert finding["down_minutes"] == 574
    assert finding["host_rebooted"] is True
    assert host_health.summary([finding]) == (
        "Host health: host was down 9 h 34 min, shutdown not clean"
    )


def test_home_assistant_crashing_alone_is_told_from_a_host_restart():
    last_seen = T0
    finding = shutdown_finding(True, last_seen, T0 + timedelta(minutes=2), T0 - timedelta(days=3))

    assert finding["host_rebooted"] is False
    assert host_health.summary([finding]) == (
        "Host health: Home Assistant was down 0 h 2 min, shutdown not clean"
    )


def test_one_issue_type_carries_every_finding():
    memory = feed(MemoryWatch(), [95, 95, 95, 95])[0]
    containers = host_health.top_containers(
        [
            {"name": "Supervisor", "memory_usage": 200 * 1024**2, "memory_percent": 5.0},
            {"name": "Home Assistant Core", "memory_usage": 900 * 1024**2,
             "memory_percent": 22.5},
        ]
    )

    issue = host_health.build_issue([memory], T0, T0 + STEP, None, containers)

    assert issue["type"] == "host_health"
    assert issue["schema_version"] == 1
    assert issue["summary"] == "Host health: memory above 90% for 30 min (peak 95%)"
    assert set(issue["details"]) == {"memory", "containers"}
    assert [c["name"] for c in issue["details"]["containers"]] == [
        "Home Assistant Core",
        "Supervisor",
    ]
