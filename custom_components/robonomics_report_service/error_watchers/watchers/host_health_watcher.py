"""Reads the host for host_health.py: memory, the recorder's runs, the Supervisor.

It only reads. Memory comes from /proc/meminfo every few minutes; the
Supervisor is asked for per-container memory only when there is something to
report, and the recorder once at start. What it keeps (daily means, what was
already reported) is saved once a day and once per start: a few small writes
a day.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import host_health
from ...const import HOST_HEALTH_STORAGE_KEY
from ...utils.ha_storage import async_load_from_store, async_save_to_store
from .error_watcher import ErrorWatcher

_LOGGER = logging.getLogger(__name__)

MEMINFO_PATH = "/proc/meminfo"


def read_previous_run(
    session: Session, started: datetime
) -> tuple[bool, datetime | None] | None:
    """How the run before `started` ended, and when it was last seen alive.

    None when there is no earlier run (a new database). The recorder marks a
    run that was still open at the next start as closed incorrectly; its end
    is then set to that next start, so "last seen" is taken from the last
    state or event written before it.
    """

    from homeassistant.components.recorder.db_schema import Events, RecorderRuns, States
    from homeassistant.components.recorder.models import process_timestamp

    previous = session.execute(
        select(RecorderRuns)
        .where(RecorderRuns.start < started)
        .order_by(RecorderRuns.start.desc())
        .limit(1)
    ).scalar_one_or_none()
    if previous is None:
        return None

    before = started.timestamp()
    last_state = session.execute(
        select(func.max(States.last_updated_ts)).where(States.last_updated_ts < before)
    ).scalar()
    last_event = session.execute(
        select(func.max(Events.time_fired_ts)).where(Events.time_fired_ts < before)
    ).scalar()
    seen = [ts for ts in (last_state, last_event) if ts is not None]
    last_seen = dt_util.utc_from_timestamp(max(seen)) if seen else None
    # Nothing written during the run: fall back to when it began.
    if last_seen is None or last_seen < process_timestamp(previous.start):
        last_seen = process_timestamp(previous.start)
    return bool(previous.closed_incorrect), last_seen


class HostHealthWatcher(ErrorWatcher):
    """Memory and unclean shutdowns of the host, reported as host_health."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass)
        self._memory = host_health.MemoryWatch()
        self._timer = None
        self._started = dt_util.utcnow()
        self._period_start = self._started
        self._saved_day: str | None = None
        # The recorder run whose predecessor was already checked: reloading the
        # integration must not report the same shutdown again.
        self._shutdown_checked: str | None = None

    def setup(self) -> None:
        self._timer = async_track_time_interval(
            self.hass, self._sample, host_health.SAMPLE_INTERVAL
        )
        self.hass.async_create_task(self._async_start())

    def remove(self) -> None:
        if self._timer is not None:
            self._timer()
            self._timer = None

    async def _async_start(self) -> None:
        try:
            saved = await async_load_from_store(self.hass, HOST_HEALTH_STORAGE_KEY)
        except Exception:
            _LOGGER.debug("Host health: no saved daily means", exc_info=True)
            saved = {}
        self._memory.daily = {
            day: [float(v[0]), int(v[1])] for day, v in (saved.get("daily") or {}).items()
        }
        self._memory.growth_reported_on = saved.get("growth_reported_on")
        self._shutdown_checked = saved.get("shutdown_checked")
        self._saved_day = dt_util.utcnow().date().isoformat()

        await self._check_last_shutdown()
        await self._sample()

    async def _check_last_shutdown(self) -> None:
        try:
            from homeassistant.helpers.recorder import get_instance, session_scope

            instance = get_instance(self.hass)
            if not await instance.async_db_ready:
                return
            started = instance.recorder_runs_manager.recording_start
            if self._shutdown_checked == started.isoformat():
                return

            def _read() -> tuple[bool, datetime | None] | None:
                with session_scope(session=instance.get_session(), read_only=True) as session:
                    return read_previous_run(session, started)

            previous = await instance.async_add_executor_job(_read)
        except Exception:
            _LOGGER.debug("Host health: cannot read the recorder's runs", exc_info=True)
            return
        self._shutdown_checked = started.isoformat()
        await self._persist()
        if previous is None:
            return

        closed_incorrect, last_seen = previous
        finding = host_health.shutdown_finding(
            closed_incorrect, last_seen, started, await self._host_booted()
        )
        if finding is not None:
            await self._report([finding], last_seen or started, started)

    async def _sample(self, _: Any = None) -> None:
        try:
            text = await self.hass.async_add_executor_job(_read_meminfo)
        except OSError:
            _LOGGER.debug("Host health: %s is not readable", MEMINFO_PATH, exc_info=True)
            return
        sample = host_health.parse_meminfo(text)
        if sample is None:
            return

        now = dt_util.utcnow()
        findings = self._memory.add(sample, now)
        await self._save_daily(now)
        if findings:
            if any(f["finding"] == "growth" for f in findings):
                # Saved at once, so a restart today does not report it again.
                await self._persist()
            await self._report(findings, self._period_start, now)
            self._period_start = now

    async def _save_daily(self, now: datetime) -> None:
        """Once a day, when the day changes: the watcher's regular write."""

        today = now.date().isoformat()
        if today == self._saved_day:
            return
        self._saved_day = today
        self._memory.prune(now.date())
        await self._persist()

    async def _persist(self) -> None:
        try:
            await async_save_to_store(
                self.hass,
                HOST_HEALTH_STORAGE_KEY,
                {
                    "daily": self._memory.daily,
                    "growth_reported_on": self._memory.growth_reported_on,
                    "shutdown_checked": self._shutdown_checked,
                },
            )
        except Exception:
            _LOGGER.debug("Host health: daily means not saved", exc_info=True)

    async def _report(
        self, findings: list[dict[str, Any]], start: datetime, end: datetime
    ) -> None:
        containers = None
        if any(f["finding"] in ("memory", "growth") for f in findings):
            containers = await self._containers()
        issue = host_health.build_issue(
            findings, start, end, await self._get_email(), containers
        )
        _LOGGER.debug("Host health: sending report (%s)", issue["summary"])
        await self._send_report(issue)

    def _supervisor(self):
        """The Supervisor client, where there is a Supervisor (HAOS, Supervised)."""

        if "hassio" not in self.hass.config.components:
            return None
        from homeassistant.components.hassio import get_supervisor_client

        return get_supervisor_client(self.hass)

    async def _host_booted(self) -> datetime | None:
        try:
            client = self._supervisor()
            if client is None:
                return None
            info = await client.host.info()
        except Exception:
            _LOGGER.debug("Host health: no host info from the Supervisor", exc_info=True)
            return None
        if not info.boot_timestamp:
            return None
        # The Supervisor gives it in microseconds.
        return dt_util.utc_from_timestamp(info.boot_timestamp / 1_000_000)

    async def _containers(self) -> list[dict[str, Any]] | None:
        """Memory per container, asked only when there is a report to send."""

        try:
            client = self._supervisor()
            if client is None:
                return None
            stats = [
                {"name": "Home Assistant Core", **(await client.homeassistant.stats()).to_dict()},
                {"name": "Supervisor", **(await client.supervisor.stats()).to_dict()},
            ]
            for addon in await client.addons.list():
                if addon.state != "started":
                    continue
                addon_stats = await client.addons.addon_stats(addon.slug)
                stats.append({"name": addon.name, **addon_stats.to_dict()})
        except Exception:
            _LOGGER.debug("Host health: no container stats from the Supervisor", exc_info=True)
            return None
        return host_health.top_containers(stats)


def _read_meminfo() -> str:
    with open(MEMINFO_PATH, encoding="ascii") as file:
        return file.read()
