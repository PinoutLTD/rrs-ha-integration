import asyncio
import hashlib
import logging
import os
import time
from datetime import timedelta
from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.components.system_log import DOMAIN as SYSTEM_LOG_DOMAIN
from homeassistant.components.system_log import EVENT_SYSTEM_LOG
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from ...const import (
    CHECK_LOGS_TIMEOUT,
    DOMAIN,
    LOGS_BACKUP_PATH,
    LOGS_PATH,
    REPORT_FILE_MAX_BYTES,
)
from ...log_buffer import WRITE_INTERVAL_SECONDS, LogBuffer
from .error_watcher import ErrorWatcher

_LOGGER = logging.getLogger(__name__)


class LoggerHandler(ErrorWatcher):
    """Watcher that react to all warning/errors in logs"""

    def __init__(self, hass: HomeAssistant):
        super().__init__(hass)

        self._event_listener = None

        self._flush_timer_listener = None
        self._period_start = dt_util.utcnow()

        # Buffer for accumulated log records
        self._accumulated_records: dict[str, dict[str, Any]] = {}

        self._acc_lock = asyncio.Lock()
        self._log_lock = asyncio.Lock()

        # Raw lines for the log file, written once a minute
        self._log_buffer = LogBuffer()
        self._write_timer_listener = None

        # Main log path and path for log rotation
        self._log_path = self.hass.config.path(LOGS_PATH)
        self._backup_log_path = self.hass.config.path(LOGS_BACKUP_PATH)

        if SYSTEM_LOG_DOMAIN in self.hass.data:
            self.hass.data[SYSTEM_LOG_DOMAIN].fire_event = True

    @callback
    def setup(self):
        _LOGGER.debug("LoggerHandler initialized")
        # Preppere directory for logs
        self.hass.async_create_task(self._async_prepare_log_dir())

        # Create listener for event with appearing HA log
        self._event_listener = self.hass.bus.async_listen(
            EVENT_SYSTEM_LOG, self._catch_new_log
        )

        # Create timer to flush accumulated log records to send_report service
        self._flush_timer_listener = async_track_time_interval(
            self.hass, self._flush, timedelta(minutes=CHECK_LOGS_TIMEOUT)
        )

        self._write_timer_listener = async_track_time_interval(
            self.hass, self._write_buffered, timedelta(seconds=WRITE_INTERVAL_SECONDS)
        )

    @callback
    def remove(self):
        if self._event_listener is not None:
            self._event_listener()
            self._event_listener = None

        if self._flush_timer_listener is not None:
            self._flush_timer_listener()
            self._flush_timer_listener = None

        if self._write_timer_listener is not None:
            self._write_timer_listener()
            self._write_timer_listener = None
        # What is still in memory, repeats included, goes to the file now.
        self.hass.async_create_task(self._write_buffered(everything=True))

        _LOGGER.debug("LoggerHandler removed")

    async def _async_prepare_log_dir(self) -> None:
        try:
            await self.hass.async_add_executor_job(self._ensure_log_dir)
        except Exception:
            _LOGGER.debug(
                "Failed to prepare local log directory", exc_info=True
            )

    async def _catch_new_log(self, log_event: Event) -> None:
        """Catch needed logs and add them to the log buffer"""

        log = log_event.data

        try:
            await self._write_raw_log_line(log)
        except Exception:
            _LOGGER.debug(
                "LoggerHandler failed to write raw log line", exc_info=True
            )

        await self._collect_issue_record(log)

    async def _collect_issue_record(self, log: dict[str, Any]) -> None:
        # Check only logs that are not related to the report service
        name = log.get("name")
        if isinstance(name, str) and DOMAIN in name:
            return

        # Accept only critical, error and warning levels of logs
        level = log.get("level")
        if level not in ("ERROR", "CRITICAL", "WARNING"):
            return

        # Gather other related fields of log
        source = log.get("source")
        message = log.get("message")

        # Create unique signature of log for deduplication
        # based on name, level and message
        signature_src = f"{name or ''}|{level or ''}|{message or ''}"
        signature = hashlib.sha256(
            signature_src.encode("utf-8", "ignore")
        ).hexdigest()[:16]

        event_ts = log.get("timestamp")
        if event_ts:
            ts = dt_util.utc_from_timestamp(event_ts).isoformat()
        else:
            ts = dt_util.utcnow().isoformat()

        # Add log record if it is unique
        # or modify count and last seen time otherwise
        async with self._acc_lock:
            entry = self._accumulated_records.get(signature)
            if entry is None:
                self._accumulated_records[signature] = {
                    "signature": signature,
                    "count": 1,
                    "first_seen": ts,
                    "last_seen": ts,
                    "level": level,
                    "name": name,
                    "source": source,
                    "message": message,
                }
            else:
                entry["count"] += 1
                entry["last_seen"] = ts

    async def _write_raw_log_line(self, log: dict[str, Any]) -> None:
        """Write one system_log event to integration log file"""

        event_ts = log.get("timestamp")
        if event_ts:
            ts = dt_util.utc_from_timestamp(event_ts).isoformat()
        else:
            ts = dt_util.utcnow().isoformat()

        payload: dict[str, Any] = {
            "ts": ts,
            "level": log.get("level"),
            "name": log.get("name"),
            "source": log.get("source"),
            "message": log.get("message"),
        }

        exception = log.get("exception")
        if exception:
            payload["exception"] = exception

        # Written once a minute, repeats folded (log_buffer.py).
        self._log_buffer.add(payload, time.monotonic())

    async def _write_buffered(self, _=None, everything: bool = False) -> None:
        lines = self._log_buffer.drain(time.monotonic(), everything)
        if not lines:
            return
        async with self._log_lock:
            await self.hass.async_add_executor_job(self._append_lines, lines)

    def _append_lines(self, lines: list[str]) -> None:
        for line in lines:
            self._append_log_with_rotation(line)

    async def _flush(self, _=None) -> None:
        """Send one accumulated report per time window"""

        # The report carries the log file: what is buffered goes there first.
        await self._write_buffered()
        async with self._acc_lock:
            # If there were no logs, restart the timer
            if not self._accumulated_records:
                self._period_start = dt_util.utcnow()
                _LOGGER.debug(
                    "LoggerHandler did not found any significant logs"
                )
                return

            period_end = dt_util.utcnow()

            entries = list(self._accumulated_records.values())

            # Statistics
            total_number = sum(entry["count"] for entry in entries)
            unique_number = len(entries)

            # Sort by occurrence and keep only top 25
            entries.sort(key=lambda entry: entry["count"], reverse=True)
            top_entries = entries[:25]

            # Calc occurrences by level
            by_level_events: dict[str, int] = {}
            for entry in entries:
                level = entry.get("level") or "UNKNOWN"
                by_level_events[level] = by_level_events.get(level, 0) + int(
                    entry.get("count", 0)
                )

            # Gather issue
            email = await self._get_email()
            issue: dict[str, Any] = {
                "type": "accumulated_system_log_problems",
                "email": email,
                "schema_version": 1,
                "ts_start": self._period_start.isoformat(),
                "ts_end": period_end.isoformat(),
                "summary": (
                    f"System log: {unique_number} unique issues, "
                    f"{total_number} occurrences "
                    f"(last {CHECK_LOGS_TIMEOUT} min)"
                ),
                "details": {
                    "logs_timeout_minutes": CHECK_LOGS_TIMEOUT,
                    "total_events": total_number,
                    "unique_events": unique_number,
                    "by_level_events": by_level_events,
                    "top_events": top_entries,
                },
            }

            # Reset buffer for next time window
            self._accumulated_records = {}
            self._period_start = period_end

        # Outside acyncio lock, trigger report sending
        _LOGGER.debug(
            "LoggerHandler is sending report (unique=%d, total=%d)",
            unique_number,
            total_number,
        )
        await self._send_report(issue)

    def _ensure_log_dir(self) -> None:
        os.makedirs(os.path.dirname(self._log_path), exist_ok=True)

    def _append_log_with_rotation(self, line: str) -> None:
        """Append line to current log file with size-based rotation"""

        self._ensure_log_dir()

        encoded_line = line.encode("utf-8", errors="replace")

        if len(encoded_line) > REPORT_FILE_MAX_BYTES:
            encoded_line = encoded_line[-REPORT_FILE_MAX_BYTES:]

        current_logfile_size = (
            os.path.getsize(self._log_path)
            if os.path.isfile(self._log_path)
            else 0
        )

        if current_logfile_size + len(encoded_line) > REPORT_FILE_MAX_BYTES:
            if os.path.isfile(self._backup_log_path):
                os.remove(self._backup_log_path)
            if os.path.isfile(self._log_path):
                os.replace(self._log_path, self._backup_log_path)

        with open(self._log_path, "ab") as logfile:
            logfile.write(encoded_line)
