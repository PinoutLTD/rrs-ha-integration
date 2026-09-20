"""A daily "the site is alive" record in the datalog.

Reports are sent only when something is wrong, which makes a silent site
ambiguous: it reads the same whether the home is healthy or the integration
stopped working months ago. The heartbeat turns the absence of a signal into
an event the connector can act on.

It does not go through IPFS: the payload is a few dozen bytes of JSON written
straight into the datalog. Nothing about the home is in it — only that this
address is alive, which version runs there and when it spoke — so there is
nothing to encrypt, and it still arrives when the report path itself is
broken (revoked Pinata keys, a gateway outage).

Sites are spread across the day by an offset derived from the site's own
address, so a hundred homes do not all publish in the same minute.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later, async_track_point_in_time
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:  # importing it at runtime would pull in Pinata for a type hint
    from .robonomics import Robonomics

_LOGGER = logging.getLogger(__name__)

HEARTBEAT_TYPE = "hb"


def heartbeat_payload(version: str, ha_version: str, now: datetime) -> dict:
    """What goes into the datalog: the minimum that proves life."""

    return {
        "t": HEARTBEAT_TYPE,
        "v": version,
        "ha": ha_version,
        "ts": int(now.timestamp()),
    }


def send_offset(address: str, interval: timedelta) -> timedelta:
    """A site's fixed place inside the interval, derived from its address."""

    digest = hashlib.sha256(address.encode("utf-8")).digest()
    seconds = int.from_bytes(digest[:4], "big") % max(int(interval.total_seconds()), 1)
    return timedelta(seconds=seconds)


def next_send_time(address: str, interval: timedelta, now: datetime) -> datetime:
    """The next slot of this site, strictly after `now`.

    Slots sit on a fixed grid (epoch + interval) plus the site's offset, so a
    restart does not shift the site's place in the day and does not let a
    restarting site publish more often than the interval.
    """

    period = int(interval.total_seconds())
    offset = int(send_offset(address, interval).total_seconds())
    elapsed = int(now.timestamp())
    slot = ((elapsed - offset) // period + 1) * period + offset
    return datetime.fromtimestamp(slot, tz=now.tzinfo or dt_util.UTC)


class Heartbeat:
    """Schedules the heartbeat: once shortly after start, then every interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        robonomics: Robonomics,
        version: str,
        interval: timedelta,
        startup_delay: timedelta,
    ) -> None:
        self.hass = hass
        self.robonomics = robonomics
        self.version = version
        self.interval = interval
        self.startup_delay = startup_delay
        self._cancel: Callable[[], None] | None = None

    def start(self) -> None:
        """First beat soon after start: a restart should confirm life at once."""

        self._cancel = async_call_later(
            self.hass, self.startup_delay, self._handle_time
        )

    def stop(self) -> None:
        if self._cancel is not None:
            self._cancel()
            self._cancel = None

    async def _handle_time(self, now: datetime) -> None:
        self._cancel = None
        await self.send()
        self._schedule_next()

    def _schedule_next(self) -> None:
        when = next_send_time(
            self.robonomics.sender_address, self.interval, dt_util.utcnow()
        )
        self._cancel = async_track_point_in_time(self.hass, self._handle_time, when)
        _LOGGER.debug("Next heartbeat at %s", when.isoformat())

    async def send(self) -> None:
        payload = heartbeat_payload(self.version, HA_VERSION, dt_util.utcnow())
        try:
            # Not a report: there is nothing on Pinata to clean up if it fails.
            await self.robonomics.send_datalog(payload, cleanup_pinata=False)
        except Exception:
            # A missed beat is the connector's business, not an error to retry
            # here: the next one is a day away and silence is the signal.
            _LOGGER.warning("Heartbeat was not sent", exc_info=True)
