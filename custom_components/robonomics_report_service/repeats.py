"""Periodic reports that would only repeat themselves.

With an hourly interval a site that always logs the same warnings, or always
has the same unavailable entities, would send the same report every hour:
a record of the pool's free weight, a few megabytes on Pinata and a note on
the ticket each time, with nothing new in it. So a report goes out when it
says something the last one did not, and otherwise once a day, as a reminder
that the problem is still there.

What counts as new is up to the caller:
- log signatures: a signature not in the last report (`new_only`); the counts
  of the old ones grow every hour and are not news;
- unavailable entities: any change of the set, a recovery included.

With the daily interval every check is due, so the reports are as before.
Kept in memory: after a restart the first report goes out again.
"""

from __future__ import annotations

from dataclasses import dataclass

DAY_MINUTES = 24 * 60


@dataclass
class Repeats:
    interval_minutes: int
    _sent: frozenset[str] | None = None
    _quiet: int = 0  # checks skipped since the last report

    def due(self, keys: frozenset[str], new_only: bool = False) -> int:
        """0 to skip this check, else how many checks the report covers."""

        if self._sent is None:
            changed = True
        elif new_only:
            changed = not keys <= self._sent
        else:
            changed = keys != self._sent
        every = max(1, DAY_MINUTES // self.interval_minutes)
        if not changed and self._quiet + 1 < every:
            self._quiet += 1
            return 0
        covered, self._quiet, self._sent = self._quiet + 1, 0, keys
        return covered

    def forget(self) -> None:
        """Nothing to report: whatever comes next is new."""

        self._sent, self._quiet = None, 0
