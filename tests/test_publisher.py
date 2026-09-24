"""The publishing queue: what is retried, what is dropped, what survives a restart."""

import asyncio

import pytest
from publisher import MAX_AGE_SECONDS, MAX_QUEUE, RETRY_DELAYS, DatalogPublisher
from robonomicsinterface import (
    ConnectionLost,
    DatalogItem,
    ExtrinsicFailed,
    ExtrinsicOutcomeUnknown,
    InvalidTransaction,
    Keypair,
)

from .conftest import SENDER_SEED

CID = "QmWue3YfuZvuRvgcNb4vZuheX9TaZ9E1b8aCdxSoaGTbVN"
CID_2 = "QmUqNnzdZnic61UYTuKT9EzBNzMW6jc5uHSFk4Xzd3iM93"
NOW = 1_789_905_600.0
OWNER = "4GuDRQsfH71yHM9aL4Kfu3SCzW6cFDGi45k9VYGNNis9v76D"  # fixture account


def refused() -> ExtrinsicFailed:
    return ExtrinsicFailed(
        "RWS.NotLinkedDevice: the signer is not a device of this subscription",
        pallet="RWS",
        error="NotLinkedDevice",
        docs="",
        result=None,
    )


class FakeDatalog:
    """The chain: `outcomes` are what the next `record` calls do."""

    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.recorded: list[tuple[str, str | None]] = []
        self.on_chain: list[DatalogItem] = []

    async def record(self, keypair, data, *, subscription_owner=None):
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome == "lands, then unknown":
            self.on_chain.append(DatalogItem(len(self.on_chain), int(NOW * 1000), data.encode()))
            outcome = ExtrinsicOutcomeUnknown("0xabc", "connection lost")
        if isinstance(outcome, Exception):
            raise outcome
        self.recorded.append((data, subscription_owner))
        self.on_chain.append(DatalogItem(len(self.on_chain), int(NOW * 1000), data.encode()))

    async def items(self, address):
        return list(self.on_chain)


class Harness:
    def __init__(self, datalog: FakeDatalog, saved: list | None = None) -> None:
        self.datalog = datalog
        self.saved: list[list[dict]] = []
        self.dropped: list[tuple[str, str]] = []
        self.timers: list[tuple[float, object]] = []
        self.now = NOW
        self.publisher = DatalogPublisher(
            datalog,
            Keypair.from_secret(SENDER_SEED),
            OWNER,
            save=self._save,
            on_dropped=self._dropped,
            schedule=self._schedule,
            clock=lambda: self.now,
        )
        if saved:
            self.publisher.restore(saved)

    async def _save(self, pending):
        self.saved.append(pending)

    async def _dropped(self, item, reason):
        self.dropped.append((item.payload, reason))

    def _schedule(self, delay, action):
        self.timers.append((delay, action))
        return lambda: None

    async def settle(self) -> None:
        worker = self.publisher._worker
        if worker is not None:
            await worker

    async def fire_timer(self) -> None:
        delay, action = self.timers.pop(0)
        self.now += delay
        action()
        await self.settle()


@pytest.mark.asyncio
async def test_a_report_is_published_through_the_subscription():
    harness = Harness(FakeDatalog())

    await harness.publisher.publish(CID)
    await harness.settle()

    assert harness.datalog.recorded == [(CID, OWNER)]
    assert harness.publisher.pending == []
    assert harness.saved[-1] == []


@pytest.mark.asyncio
async def test_a_network_failure_keeps_the_report_and_tries_again_later():
    harness = Harness(FakeDatalog(ConnectionLost("closed")))

    await harness.publisher.publish(CID)
    await harness.settle()

    assert harness.datalog.recorded == []
    assert [item.payload for item in harness.publisher.pending] == [CID]
    assert harness.timers[0][0] == RETRY_DELAYS[0]
    assert harness.saved[-1][0]["payload"] == CID  # survives a restart
    assert harness.dropped == []

    await harness.fire_timer()

    assert harness.datalog.recorded == [(CID, OWNER)]
    assert harness.publisher.pending == []


@pytest.mark.asyncio
async def test_a_refusal_drops_the_report_so_its_files_can_be_unpinned():
    harness = Harness(FakeDatalog(refused()))

    await harness.publisher.publish(CID)
    await harness.settle()

    assert harness.publisher.pending == []
    assert harness.timers == []
    ((payload, reason),) = harness.dropped
    assert payload == CID and "NotLinkedDevice" in reason


@pytest.mark.asyncio
async def test_a_missing_account_is_a_refusal_too():
    missing = InvalidTransaction("Payment", "the signer does not exist on chain")
    harness = Harness(FakeDatalog(missing))

    await harness.publisher.publish(CID)
    await harness.settle()

    assert [payload for payload, _ in harness.dropped] == [CID]


@pytest.mark.asyncio
async def test_a_record_that_landed_despite_an_unknown_outcome_is_not_sent_twice():
    harness = Harness(FakeDatalog("lands, then unknown"))

    await harness.publisher.publish(CID)
    await harness.settle()
    assert harness.publisher.pending[0].maybe_sent is True

    await harness.fire_timer()

    assert harness.publisher.pending == []
    assert len(harness.datalog.on_chain) == 1  # found on chain, not published again


@pytest.mark.asyncio
async def test_an_unknown_outcome_that_did_not_land_is_sent_again():
    harness = Harness(FakeDatalog(ExtrinsicOutcomeUnknown("0xabc", "timeout")))

    await harness.publisher.publish(CID)
    await harness.settle()
    await harness.fire_timer()

    assert harness.datalog.recorded == [(CID, OWNER)]


@pytest.mark.asyncio
async def test_a_heartbeat_is_not_repeated_or_saved():
    harness = Harness(FakeDatalog(ConnectionLost("closed")))

    await harness.publisher.publish('{"t":"hb"}', report=False)
    await harness.settle()

    assert harness.publisher.pending == []
    assert harness.timers == []
    assert all(saved == [] for saved in harness.saved)


@pytest.mark.asyncio
async def test_pauses_grow_and_a_report_is_given_up_after_the_silence_threshold():
    failures = [ConnectionLost("closed")] * 200
    harness = Harness(FakeDatalog(*failures))

    await harness.publisher.publish(CID)
    await harness.settle()
    delays = []
    while harness.timers:
        delays.append(harness.timers[0][0])
        await harness.fire_timer()

    assert delays[: len(RETRY_DELAYS)] == list(RETRY_DELAYS)
    assert set(delays[len(RETRY_DELAYS) :]) == {RETRY_DELAYS[-1]}
    assert harness.now - NOW >= MAX_AGE_SECONDS
    ((payload, reason),) = harness.dropped
    assert payload == CID and "given up" in reason


@pytest.mark.asyncio
async def test_reports_saved_before_a_restart_are_published_first():
    saved = [{"payload": CID, "report": True, "queued_at": NOW - 60, "attempts": 2}]
    harness = Harness(FakeDatalog(), saved=saved)

    await harness.publisher.publish(CID_2)
    await harness.settle()

    assert [data for data, _ in harness.datalog.recorded] == [CID, CID_2]


@pytest.mark.asyncio
async def test_the_queue_is_bounded_and_drops_the_oldest():
    harness = Harness(FakeDatalog(*[ConnectionLost("closed")] * 5))
    await harness.publisher.publish("Qm-first")
    await harness.settle()  # waiting for its retry

    for number in range(MAX_QUEUE):
        await harness.publisher.publish(f"Qm-{number}")

    assert len(harness.publisher.pending) == MAX_QUEUE
    assert [payload for payload, _ in harness.dropped] == ["Qm-first"]


@pytest.mark.asyncio
async def test_closing_stops_the_worker():
    never = asyncio.Event()

    class Hanging(FakeDatalog):
        async def record(self, keypair, data, *, subscription_owner=None):
            await never.wait()

    harness = Harness(Hanging())
    await harness.publisher.publish(CID)
    await asyncio.sleep(0)

    await harness.publisher.close()

    assert harness.publisher._worker.done()
    assert [item.payload for item in harness.publisher.pending] == [CID]
