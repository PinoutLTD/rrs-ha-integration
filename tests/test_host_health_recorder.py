"""Reading how the last run ended from the recorder's own schema."""

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("homeassistant", reason="reads the recorder's schema")

from homeassistant.components.recorder.db_schema import (  # noqa: E402
    Base,
    Events,
    RecorderRuns,
    States,
)
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from custom_components.robonomics_report_service.error_watchers.watchers.host_health_watcher import (  # noqa: E402, E501
    read_previous_run,
)

LAST_SEEN = datetime(2026, 9, 28, 19, 15, 54, tzinfo=UTC)
STARTED = datetime(2026, 9, 29, 4, 49, 30, tzinfo=UTC)


@pytest.fixture(name="session")
def fixture_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def run(session: Session, start: datetime, end: datetime | None, incorrect: bool) -> None:
    session.add(RecorderRuns(start=start, end=end, closed_incorrect=incorrect, created=start))


def test_a_run_closed_incorrectly_and_when_it_was_last_seen(session):
    # As the recorder leaves it after a freeze: the open run is closed at the
    # next start and marked; the current run has begun.
    run(session, STARTED - timedelta(days=1), STARTED, True)
    run(session, STARTED, None, False)
    session.add(States(state="on", last_updated_ts=LAST_SEEN.timestamp() - 60))
    session.add(Events(time_fired_ts=LAST_SEEN.timestamp()))
    # Written by the new run: not "last seen" of the old one.
    session.add(States(state="on", last_updated_ts=STARTED.timestamp() + 5))
    session.commit()

    closed_incorrect, last_seen = read_previous_run(session, STARTED)

    assert closed_incorrect is True
    assert last_seen == LAST_SEEN


def test_a_clean_run_is_read_as_clean(session):
    run(session, STARTED - timedelta(days=1), STARTED - timedelta(minutes=1), False)
    run(session, STARTED, None, False)
    session.commit()

    closed_incorrect, last_seen = read_previous_run(session, STARTED)

    assert closed_incorrect is False
    # Nothing was written during it: the run's start stands in.
    assert last_seen == STARTED - timedelta(days=1)


def test_a_new_database_has_no_previous_run(session):
    run(session, STARTED, None, False)
    session.commit()

    assert read_previous_run(session, STARTED) is None
