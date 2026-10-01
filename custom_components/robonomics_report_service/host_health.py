"""Watching the host itself: its memory, and whether the last run ended cleanly.

The entities check and the log watcher see Home Assistant from the inside; a
host that slowly runs out of memory looks healthy to both until it stops
answering, and after it comes back nothing says it was gone. One of our own
sites hung five times this way before anyone read the log by hand.

Three findings, all carried by one issue type, `host_health`:

- **memory** — used memory stayed above the limit for a sustained time; once
  per episode, which ends only when memory falls well below the limit;
- **growth** — the daily mean has been rising day after day, before the limit
  is reached: on the site above memory grew for a week before each hang;
- **shutdown** — the previous run did not end cleanly (crash, freeze, power
  loss): when it was last seen alive and when it came back.

This module only decides; reading memory, the recorder and the Supervisor is
done by the watcher. Nothing here imports Home Assistant, so the rules are
tested on their own.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

ISSUE_TYPE = "host_health"
SCHEMA_VERSION = 1

# Used memory above this, for this long, is reported.
MEMORY_LIMIT_PERCENT = 90.0
MEMORY_SUSTAINED = timedelta(minutes=30)
# An episode ends only below this, so memory hovering at the limit is one
# report, not one every half hour.
MEMORY_REARM_PERCENT = 85.0
SAMPLE_INTERVAL = timedelta(minutes=10)

# Growth: the daily mean rose on each of this many complete days in a row...
GROWTH_DAYS = 4
# ...by at least this much in total, and ended at least this high. Below the
# floor a rising mean is a system settling after boot, not a leak.
GROWTH_MIN_POINTS = 10.0
GROWTH_FLOOR_PERCENT = 70.0
# Daily means kept across restarts; enough to see a week-long climb.
DAYS_KEPT = 14


@dataclass(frozen=True)
class MemorySample:
    total_bytes: int
    available_bytes: int
    swap_total_bytes: int
    swap_free_bytes: int

    @property
    def used_percent(self) -> float:
        return 100.0 * (self.total_bytes - self.available_bytes) / self.total_bytes

    @property
    def swap_used_bytes(self) -> int:
        return self.swap_total_bytes - self.swap_free_bytes


def parse_meminfo(text: str) -> MemorySample | None:
    """Memory of the host as the kernel counts it (`/proc/meminfo`).

    Inside the Home Assistant container this is the host's memory, not a
    container limit. None when the numbers needed are not there.
    """

    values: dict[str, int] = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if not parts:
            continue
        try:
            # The kernel reports kB meaning KiB.
            values[name.strip()] = int(parts[0]) * 1024
        except ValueError:
            continue
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return None
    return MemorySample(
        total_bytes=total,
        available_bytes=available,
        swap_total_bytes=values.get("SwapTotal", 0),
        swap_free_bytes=values.get("SwapFree", 0),
    )


def mib(value: int) -> int:
    return round(value / (1024 * 1024))


@dataclass
class MemoryWatch:
    """Decides, sample by sample, what about memory is worth a report.

    `daily` holds the running sum and count of used percent per day; the
    watcher saves it once a day, so a restart of Home Assistant does not hide
    a climb that started before it (the memory belongs to the host, and a
    restart of Home Assistant alone may not free it).
    """

    limit: float = MEMORY_LIMIT_PERCENT
    sustained: timedelta = MEMORY_SUSTAINED
    rearm: float = MEMORY_REARM_PERCENT
    daily: dict[str, list[float]] = field(default_factory=dict)
    growth_reported_on: str | None = None

    _above_since: datetime | None = None
    _reported: bool = False
    _peak: tuple[float, datetime] | None = None
    _recent: deque[tuple[datetime, float]] = field(default_factory=deque)

    def add(self, sample: MemorySample, at: datetime) -> list[dict[str, Any]]:
        """Take a sample; return the findings it completes, if any."""

        used = sample.used_percent
        findings: list[dict[str, Any]] = []

        self._recent.append((at, used))
        while self._recent and at - self._recent[0][0] > timedelta(hours=24):
            self._recent.popleft()

        day = at.date().isoformat()
        total = self.daily.setdefault(day, [0.0, 0])
        total[0] += used
        total[1] += 1

        if used > self.limit:
            if self._above_since is None:
                self._above_since = at
                self._peak = (used, at)
            elif self._peak is None or used > self._peak[0]:
                self._peak = (used, at)
            if not self._reported and at - self._above_since >= self.sustained:
                self._reported = True
                findings.append(self._memory_finding(sample, at))
        elif used < self.rearm:
            self._above_since = None
            self._reported = False
            self._peak = None

        growth = self.growth(at.date())
        if growth is not None:
            findings.append(growth)
        return findings

    def _memory_finding(self, sample: MemorySample, at: datetime) -> dict[str, Any]:
        assert self._above_since is not None and self._peak is not None
        day_ago = self._recent[0]
        return {
            "finding": "memory",
            "limit_percent": self.limit,
            "above_since": self._above_since.isoformat(),
            "peak_percent": round(self._peak[0], 1),
            "peak_at": self._peak[1].isoformat(),
            "used_percent": round(sample.used_percent, 1),
            "total_mib": mib(sample.total_bytes),
            "available_mib": mib(sample.available_bytes),
            "swap_used_mib": mib(sample.swap_used_bytes),
            "swap_total_mib": mib(sample.swap_total_bytes),
            # Since the oldest sample of the last 24 h (less after a restart).
            "change_percent": round(sample.used_percent - day_ago[1], 1),
            "change_since": day_ago[0].isoformat(),
        }

    def growth(self, today: date) -> dict[str, Any] | None:
        """A steady rise of the daily mean, once per climb.

        Only complete days count: today's mean is still moving.
        """

        means = []
        for offset in range(GROWTH_DAYS, 0, -1):
            day = (today - timedelta(days=offset)).isoformat()
            total = self.daily.get(day)
            if not total or not total[1]:
                return None
            means.append((day, total[0] / total[1]))

        rising = all(b[1] > a[1] for a, b in zip(means, means[1:], strict=False))
        first, last = means[0][1], means[-1][1]
        if not rising or last - first < GROWTH_MIN_POINTS or last < GROWTH_FLOOR_PERCENT:
            return None
        # One report per climb: the same run of days does not repeat it.
        if self.growth_reported_on is not None and self.growth_reported_on >= means[0][0]:
            return None
        self.growth_reported_on = means[-1][0]
        return {
            "finding": "growth",
            "daily_mean_percent": {day: round(mean, 1) for day, mean in means},
        }

    def prune(self, today: date) -> None:
        oldest = (today - timedelta(days=DAYS_KEPT)).isoformat()
        for day in [d for d in self.daily if d < oldest]:
            del self.daily[day]


def shutdown_finding(
    closed_incorrect: bool,
    last_seen: datetime | None,
    started: datetime,
    host_booted: datetime | None,
) -> dict[str, Any] | None:
    """The previous run did not end cleanly: report when it went and came back.

    `last_seen` is the last thing the recorder wrote before `started`; with a
    crash the last few seconds may be lost, so it is "last seen alive", not
    the exact moment. `host_booted` tells a whole-host restart (power, kernel,
    a freeze someone cut the power to) from Home Assistant alone crashing.
    """

    if not closed_incorrect:
        return None
    finding: dict[str, Any] = {
        "finding": "shutdown",
        "clean": False,
        "last_seen": last_seen.isoformat() if last_seen else None,
        "started": started.isoformat(),
        "down_minutes": (
            round((started - last_seen).total_seconds() / 60) if last_seen else None
        ),
    }
    if host_booted is not None:
        finding["host_booted"] = host_booted.isoformat()
        finding["host_rebooted"] = last_seen is None or host_booted > last_seen
    return finding


def summary(findings: list[dict[str, Any]]) -> str:
    parts = []
    for finding in findings:
        kind = finding["finding"]
        if kind == "memory":
            parts.append(
                f"memory above {finding['limit_percent']:.0f}% for "
                f"{MEMORY_SUSTAINED.total_seconds() / 60:.0f} min "
                f"(peak {finding['peak_percent']:.0f}%)"
            )
        elif kind == "growth":
            means = list(finding["daily_mean_percent"].values())
            parts.append(
                f"memory growing {len(means)} days in a row "
                f"({means[0]:.0f}% → {means[-1]:.0f}%)"
            )
        elif kind == "shutdown":
            down = finding.get("down_minutes")
            where = "host" if finding.get("host_rebooted") else "Home Assistant"
            if down is None:
                parts.append(f"{where} did not shut down cleanly")
            else:
                parts.append(
                    f"{where} was down {down // 60} h {down % 60} min, "
                    "shutdown not clean"
                )
    return "Host health: " + "; ".join(parts)


def build_issue(
    findings: list[dict[str, Any]],
    ts_start: datetime,
    ts_end: datetime,
    email: str | None,
    containers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The report, one issue type whatever it found: one ticket per site."""

    details: dict[str, Any] = {finding["finding"]: finding for finding in findings}
    if containers is not None:
        details["containers"] = containers
    return {
        "type": ISSUE_TYPE,
        "email": email,
        "schema_version": SCHEMA_VERSION,
        "ts_start": ts_start.isoformat(),
        "ts_end": ts_end.isoformat(),
        "summary": summary(findings),
        "details": details,
    }


def top_containers(stats: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    """Containers by memory, largest first: who to look at."""

    ordered = sorted(stats, key=lambda s: s.get("memory_usage", 0), reverse=True)
    return [
        {
            "name": s["name"],
            "memory_mib": mib(s.get("memory_usage", 0)),
            "memory_percent": round(s.get("memory_percent", 0.0), 1),
        }
        for s in ordered[:limit]
    ]
