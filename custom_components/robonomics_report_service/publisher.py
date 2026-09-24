"""Publishing datalog records so that a network failure does not lose a report.

Every record goes through one queue, in order, and each attempt ends in one of
three ways, which robonomics-interface tells apart:

- **done** — the record is in a block;
- **retry** — the node could not be reached, or the transaction was sent and
  whether it landed is unknown. A report stays queued and is tried again after
  a pause; before sending again, the site's own datalog is read, so a record
  that did land is not published twice;
- **drop** — the chain refused it (the site is not in the subscription, the
  subscription has no allowance left, the account does not exist). Repeating
  would be refused again, so the record is dropped and the caller cleans up.

Only reports are kept for a retry and saved across restarts. A heartbeat that
misses its slot is not repeated: the next one is a day away, and silence is
exactly what the connector watches for.

Nothing here imports Home Assistant: saving, timers and tasks are passed in, so
the policy is tested on its own.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Protocol

from robonomicsinterface import (
    ExtrinsicDropped,
    ExtrinsicOutcomeUnknown,
    Keypair,
    RobonomicsError,
    RpcError,
    TransactionError,
    TransportError,
)

_LOGGER = logging.getLogger(__name__)

# Pauses between attempts, in seconds; the last one repeats.
RETRY_DELAYS = (60, 300, 900, 3600)
# Past this age the connector has already flagged the site as silent (72 h),
# so a report this old is given up rather than kept forever.
MAX_AGE_SECONDS = 72 * 3600
# A site that cannot publish for days must not grow its queue without bound.
MAX_QUEUE = 50
# Chain time and the site's clock may differ a little; a record written this
# much before it was queued still counts as ours when checking for a landing.
CLOCK_SKEW_MS = 5 * 60 * 1000


class Result(Enum):
    DONE = "done"
    RETRY = "retry"
    DROP = "drop"


@dataclass
class Pending:
    """A record waiting to be published."""

    payload: str
    # A report's payload is a CID of files pinned on Pinata; a heartbeat's is
    # its own JSON, with nothing to clean up and nothing worth retrying.
    report: bool
    queued_at: float
    attempts: int = 0
    # An earlier attempt was sent but its outcome is unknown: it may be on chain.
    maybe_sent: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Pending:
        return cls(
            payload=str(data["payload"]),
            report=bool(data.get("report", True)),
            queued_at=float(data["queued_at"]),
            attempts=int(data.get("attempts", 0)),
            maybe_sent=bool(data.get("maybe_sent", False)),
        )


class DatalogClient(Protocol):
    """What the publisher needs from `RobonomicsClient.datalog`."""

    async def record(
        self, keypair: Keypair, data: str, *, subscription_owner: str | None = None
    ) -> Any: ...

    async def items(self, address: str) -> list[Any]: ...


Save = Callable[[list[dict[str, Any]]], Awaitable[None]]
Dropped = Callable[[Pending, str], Awaitable[None]]
# schedule(delay_seconds, callback) -> cancel
Schedule = Callable[[float, Callable[[], None]], Callable[[], None]]
StartTask = Callable[[Awaitable[None]], asyncio.Task]


class DatalogPublisher:
    """One queue of datalog records for one site."""

    def __init__(
        self,
        datalog: DatalogClient,
        keypair: Keypair,
        subscription_owner: str,
        *,
        save: Save,
        on_dropped: Dropped,
        schedule: Schedule,
        start_task: StartTask = asyncio.ensure_future,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._datalog = datalog
        self._keypair = keypair
        self._owner = subscription_owner
        self._save = save
        self._on_dropped = on_dropped
        self._schedule = schedule
        self._start_task = start_task
        self._clock = clock
        self._queue: list[Pending] = []
        self._worker: asyncio.Task | None = None
        self._cancel_wake: Callable[[], None] | None = None
        self._closed = False

    @property
    def pending(self) -> list[Pending]:
        return list(self._queue)

    def restore(self, saved: list[dict[str, Any]]) -> None:
        """Reports saved before a restart go back to the front of the queue."""

        restored = []
        for data in saved:
            try:
                restored.append(Pending.from_dict(data))
            except (KeyError, TypeError, ValueError):
                _LOGGER.warning("Skipping an unreadable saved datalog record")
        self._queue[:0] = restored
        if restored:
            _LOGGER.info("%d report(s) from before the restart are queued", len(restored))

    async def publish(self, payload: str, report: bool = True) -> None:
        """Queue a record; it is published in the background."""

        self._queue.append(Pending(payload, report, self._clock()))
        # The head may be in flight right now; the oldest one behind it goes.
        busy = self._worker is not None and not self._worker.done()
        while len(self._queue) > MAX_QUEUE:
            oldest = self._queue.pop(1 if busy else 0)
            await self._drop(oldest, f"the queue holds more than {MAX_QUEUE} records")
        await self._persist()
        self.kick()

    def kick(self) -> None:
        """Start the worker now, unless it runs or waits for its next attempt."""

        if self._closed or not self._queue:
            return
        if self._worker is not None and not self._worker.done():
            return
        if self._cancel_wake is not None:
            return
        self._worker = self._start_task(self._run())

    async def close(self) -> None:
        self._closed = True
        if self._cancel_wake is not None:
            self._cancel_wake()
            self._cancel_wake = None
        if self._worker is not None and not self._worker.done():
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass

    def _wake(self) -> None:
        self._cancel_wake = None
        self.kick()

    async def _run(self) -> None:
        while self._queue and not self._closed:
            item = self._queue[0]
            result, reason = await self._attempt(item)

            if result is Result.RETRY and not item.report:
                result, reason = Result.DROP, f"heartbeat not repeated ({reason})"
            if result is Result.RETRY and self._clock() - item.queued_at > MAX_AGE_SECONDS:
                result = Result.DROP
                reason = f"given up after {item.attempts} attempts ({reason})"

            if result is Result.RETRY:
                delay = RETRY_DELAYS[min(max(item.attempts, 1), len(RETRY_DELAYS)) - 1]
                _LOGGER.info(
                    "Datalog record not published yet (%s); next attempt in %d s",
                    reason,
                    delay,
                )
                await self._persist()
                self._cancel_wake = self._schedule(delay, self._wake)
                return

            self._queue = [queued for queued in self._queue if queued is not item]
            if result is Result.DROP:
                await self._drop(item, reason)
            await self._persist()

    async def _attempt(self, item: Pending) -> tuple[Result, str]:
        try:
            if item.maybe_sent and await self._landed(item):
                _LOGGER.debug("An earlier attempt did land; not sending it again")
                return Result.DONE, ""
        except TransportError as e:
            return Result.RETRY, f"cannot check whether it landed: {e}"

        item.attempts += 1
        try:
            await self._datalog.record(
                self._keypair, item.payload, subscription_owner=self._owner
            )
        except ExtrinsicOutcomeUnknown as e:
            item.maybe_sent = True
            return Result.RETRY, str(e)
        except (TransportError, ExtrinsicDropped) as e:
            # Nothing reached a block: sending again is safe.
            return Result.RETRY, str(e)
        except RpcError as e:
            # The node answered with an error; for a submission that is often
            # its pool being busy, which passes.
            return Result.RETRY, str(e)
        except TransactionError as e:
            # The chain refused the call; its message names the reason, e.g.
            # RWS.NotLinkedDevice or InvalidTransaction::Payment.
            return Result.DROP, str(e)
        except RobonomicsError as e:
            return Result.DROP, str(e)
        _LOGGER.debug("Datalog record published")
        return Result.DONE, ""

    async def _landed(self, item: Pending) -> bool:
        since_ms = int(item.queued_at * 1000) - CLOCK_SKEW_MS
        records = await self._datalog.items(self._keypair.address)
        return any(
            record.timestamp_ms >= since_ms and record.text == item.payload
            for record in records
        )

    async def _drop(self, item: Pending, reason: str) -> None:
        _LOGGER.warning("Datalog record dropped: %s", reason)
        try:
            await self._on_dropped(item, reason)
        except Exception:
            _LOGGER.warning("Cleaning up after a dropped record failed", exc_info=True)

    async def _persist(self) -> None:
        try:
            await self._save([asdict(item) for item in self._queue if item.report])
        except Exception:
            _LOGGER.warning("Could not save the datalog queue", exc_info=True)
