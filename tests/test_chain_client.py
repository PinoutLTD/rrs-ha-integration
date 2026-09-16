"""The transport and the result check, without a chain to talk to."""

import json

import aiohttp
import pytest
from chain.client import extrinsic_failure
from chain.rpc import RobonomicsRpc, RpcError
from chain.storage import storage_key, twox128


class FakeMessage:
    type = aiohttp.WSMsgType.TEXT

    def __init__(self, payload: dict) -> None:
        self.data = json.dumps(payload)


class FakeSocket:
    """Answers with a scripted sequence, and remembers what was sent."""

    def __init__(self, answers: list[dict]) -> None:
        self.answers = list(answers)
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def receive(self, timeout=None) -> FakeMessage:
        if not self.answers:
            raise TimeoutError("no more answers")
        answer = self.answers.pop(0)
        # Let a script answer "whatever id the last request had".
        if answer.get("id") == "LAST":
            answer = dict(answer, id=self.sent[-1]["id"])
        return FakeMessage(answer)

    async def close(self) -> None:
        self.closed = True


def update(subscription: str, result) -> dict:
    return {
        "method": "author_extrinsicUpdate",
        "params": {"subscription": subscription, "result": result},
    }


class FakeSession:
    def __init__(self, socket: FakeSocket) -> None:
        self.socket = socket

    async def ws_connect(self, url, **kwargs) -> FakeSocket:
        return self.socket


async def open_rpc(answers: list[dict]) -> tuple[RobonomicsRpc, FakeSocket]:
    socket = FakeSocket(answers)
    rpc = RobonomicsRpc(FakeSession(socket), "wss://node.example")
    await rpc.__aenter__()
    return rpc, socket


# Storage keys


def test_twox128_matches_the_known_system_prefix() -> None:
    # Every Substrate chain has this prefix for the System pallet.
    assert twox128(b"System").hex() == "26aa394eea5630e07c48ae0c9558cef7"


def test_events_storage_key_is_the_known_one() -> None:
    assert storage_key("System", "Events") == (
        "0x26aa394eea5630e07c48ae0c9558cef780d41e5e16056765bc8461851072c9d7"
    )


# Transport


@pytest.mark.asyncio
async def test_request_returns_the_matching_answer() -> None:
    rpc, socket = await open_rpc(
        [
            {"jsonrpc": "2.0", "method": "someNotification", "params": {}},
            {"jsonrpc": "2.0", "id": "LAST", "result": {"specVersion": 43}},
        ]
    )

    result = await rpc.request("state_getRuntimeVersion")

    assert result == {"specVersion": 43}
    assert socket.sent[0]["method"] == "state_getRuntimeVersion"


@pytest.mark.asyncio
async def test_node_errors_carry_their_code() -> None:
    rpc, _ = await open_rpc(
        [{"id": "LAST", "error": {"code": -32601, "message": "unsafe to be called"}}]
    )

    with pytest.raises(RpcError, match="unsafe") as raised:
        await rpc.request("system_dryRun", ["0x00"])

    assert raised.value.code == -32601


@pytest.mark.asyncio
async def test_submission_waits_for_the_block() -> None:
    rpc, socket = await open_rpc(
        [
            {"id": "LAST", "result": "sub-1"},
            update("sub-1", "ready"),
            update("other", {"inBlock": "0xdead"}),
            update("sub-1", {"broadcast": ["peer"]}),
            update("sub-1", {"inBlock": "0xbeef"}),
            {"id": "LAST", "result": True},
        ]
    )

    assert await rpc.submit_and_watch("0x1234") == "0xbeef"
    assert socket.sent[-1]["method"] == "author_unwatchExtrinsic"


@pytest.mark.asyncio
async def test_a_dropped_extrinsic_is_an_error() -> None:
    rpc, _ = await open_rpc(
        [
            {"id": "LAST", "result": "sub-1"},
            update("sub-1", {"dropped": None}),
            {"id": "LAST", "result": True},
        ]
    )

    with pytest.raises(RpcError, match="dropped"):
        await rpc.submit_and_watch("0x1234")


# Result of an included extrinsic


def success(index: int) -> dict:
    return {
        "extrinsic_idx": index,
        "module_id": "System",
        "event_id": "ExtrinsicSuccess",
    }


def failure(index: int) -> dict:
    return {
        "extrinsic_idx": index,
        "module_id": "System",
        "event_id": "ExtrinsicFailed",
        "attributes": {
            "dispatch_error": {"Module": {"index": 55, "error": "0x02000000"}}
        },
    }


def test_success_is_recognised() -> None:
    assert extrinsic_failure([success(0), success(1)], 1) is None


def test_failure_is_reported_with_its_reason() -> None:
    reason = extrinsic_failure([success(0), failure(1)], 1)

    assert reason is not None
    assert "dispatch_error" in reason


def test_another_extrinsic_failing_is_not_ours() -> None:
    assert extrinsic_failure([failure(0), success(1)], 1) is None


def test_missing_result_is_not_taken_for_success() -> None:
    # Inclusion alone is not a result; saying nothing would be worse.
    assert extrinsic_failure([success(0)], 1) == (
        "the block holds no result for this extrinsic"
    )
