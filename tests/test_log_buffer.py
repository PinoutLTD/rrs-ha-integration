"""The log file is written in batches, with repeats of a message folded."""

import json

from log_buffer import REPEAT_WINDOW_SECONDS, LogBuffer


def record(ts: str, message: str = "Can't connect to 192.168.13.83", level="ERROR"):
    return {"ts": ts, "level": level, "name": "roombapy.remote_client", "message": [message]}


def lines(buffer: LogBuffer, now: float, everything: bool = False) -> list[dict]:
    return [json.loads(line) for line in buffer.drain(now, everything)]


def test_a_message_is_written_once_and_its_repeats_are_counted():
    buffer = LogBuffer()
    for i in range(20):  # every 30 s, as a device that cannot be reached
        buffer.add(record(f"t{i}"), now=i * 30)

    # Still inside the window: only the first occurrence is written.
    assert [line["ts"] for line in lines(buffer, now=19 * 30 + 1)] == ["t0"]

    # When the window closes, one line stands for the repeats.
    [folded] = lines(buffer, now=REPEAT_WINDOW_SECONDS + 1)
    assert folded["ts"] == "t19"
    assert folded["repeats"] == 19 and folded["first_ts"] == "t0"


def test_after_the_window_the_message_is_written_again():
    buffer = LogBuffer()
    buffer.add(record("a"), now=0)
    buffer.drain(now=1)
    buffer.add(record("b"), now=REPEAT_WINDOW_SECONDS + 5)

    assert [line["ts"] for line in lines(buffer, now=REPEAT_WINDOW_SECONDS + 6)] == ["b"]


def test_different_messages_are_not_folded():
    buffer = LogBuffer()
    buffer.add(record("a", "first"), now=0)
    buffer.add(record("b", "second"), now=1)
    buffer.add(record("c", "first", level="WARNING"), now=2)

    assert [line["ts"] for line in lines(buffer, now=3)] == ["a", "b", "c"]


def test_draining_everything_closes_the_windows():
    buffer = LogBuffer()
    buffer.add(record("a"), now=0)
    buffer.add(record("b"), now=10)

    [first, folded] = lines(buffer, now=11, everything=True)

    assert first["ts"] == "a" and folded["repeats"] == 1
    assert buffer.drain(now=12) == []


def test_a_single_occurrence_leaves_no_folded_line():
    buffer = LogBuffer()
    buffer.add(record("a"), now=0)
    buffer.drain(now=1)

    assert buffer.drain(now=REPEAT_WINDOW_SECONDS + 1) == []
