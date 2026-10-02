"""The integration's own log file, written in batches with repeats folded.

Every warning and error Home Assistant logs is kept in a file that goes into
reports. It used to be appended line by line: a device that cannot be reached
logs the same error every minute or two, and on one site that was thousands
of disk writes a day. On the eMMC of a Home Assistant Green those writes are
wear (HT00010).

Now lines wait in memory and are written once a minute. The first occurrence
of a message is written as it is. Repeats of the same message (level, logger
and text) within `REPEAT_WINDOW` are only counted, and when the window closes
one line stands for them: the last repeat, with `repeats` and `first_ts`. The
cost is up to a minute of lines lost when the host dies.

Nothing here imports Home Assistant; the watcher feeds it and writes what it
returns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

WRITE_INTERVAL_SECONDS = 60
REPEAT_WINDOW_SECONDS = 600


def message_key(payload: dict[str, Any]) -> str:
    return f"{payload.get('level')}|{payload.get('name')}|{payload.get('message')}"


@dataclass
class _Repeats:
    opened_at: float  # when the first occurrence was seen
    first_ts: str  # its timestamp, as written
    count: int = 0  # repeats after the first
    last: dict[str, Any] | None = None  # the last repeat


@dataclass
class LogBuffer:
    window: float = REPEAT_WINDOW_SECONDS
    _pending: list[dict[str, Any]] = field(default_factory=list)
    _recent: dict[str, _Repeats] = field(default_factory=dict)

    def add(self, payload: dict[str, Any], now: float) -> None:
        """Take one log record (`ts`, `level`, `name`, `message`, …)."""

        self._close_windows(now)
        key = message_key(payload)
        repeats = self._recent.get(key)
        if repeats is None:
            self._recent[key] = _Repeats(opened_at=now, first_ts=str(payload.get("ts")))
            self._pending.append(payload)
            return
        repeats.count += 1
        repeats.last = payload

    def drain(self, now: float, everything: bool = False) -> list[str]:
        """The lines to write now; with `everything`, close every window too."""

        self._close_windows(now, everything)
        lines = [json.dumps(p, ensure_ascii=False) + "\n" for p in self._pending]
        self._pending = []
        return lines

    def _close_windows(self, now: float, everything: bool = False) -> None:
        for key, repeats in list(self._recent.items()):
            if not everything and now - repeats.opened_at < self.window:
                continue
            del self._recent[key]
            if repeats.count and repeats.last is not None:
                self._pending.append(
                    {**repeats.last, "repeats": repeats.count, "first_ts": repeats.first_ts}
                )
