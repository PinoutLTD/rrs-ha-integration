"""A periodic report goes out when it says something new, else once a day."""

from repeats import Repeats

SAME = frozenset({"yandex|WARNING|token expired", "inels|ERROR|no answer"})


def test_the_daily_interval_sends_every_check_as_before():
    repeats = Repeats(24 * 60)

    assert [repeats.due(SAME) for _ in range(3)] == [1, 1, 1]
    assert [repeats.due(SAME, new_only=True) for _ in range(3)] == [1, 1, 1]


def test_hourly_the_same_logs_go_out_once_a_day():
    repeats = Repeats(60)

    sent = [repeats.due(SAME, new_only=True) for _ in range(49)]

    # The first check, then a reminder covering the 24 checks since.
    assert [i for i, covered in enumerate(sent) if covered] == [0, 24, 48]
    assert sent[24] == 24


def test_a_new_log_signature_goes_out_at_once_and_a_quiet_one_does_not():
    repeats = Repeats(60)
    repeats.due(SAME, new_only=True)

    # One of the old messages did not come this hour: nothing new.
    assert repeats.due(frozenset({"inels|ERROR|no answer"}), new_only=True) == 0
    assert repeats.due(SAME | {"dhcp|ERROR|new device"}, new_only=True) == 2


def test_any_change_of_the_unavailable_entities_goes_out():
    repeats = Repeats(60)
    repeats.due(frozenset({"sensor.a", "sensor.b"}))

    assert repeats.due(frozenset({"sensor.a", "sensor.b"})) == 0
    # A recovery is news too.
    assert repeats.due(frozenset({"sensor.a"})) == 2


def test_after_all_is_well_the_same_problem_is_news_again():
    repeats = Repeats(60)
    repeats.due(frozenset({"sensor.a"}))
    repeats.forget()

    assert repeats.due(frozenset({"sensor.a"})) == 1
