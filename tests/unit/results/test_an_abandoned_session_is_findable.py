"""A calibration that never closed has to be findable and closable.

A session is opened ``running`` and closed in a ``finally``. A SIGKILL, a power
cut or a lost machine runs neither, so the row stays ``running`` for good: no end
date, no outcome, and every listing shows a calibration that is not happening.

Nothing looked for those rows. The index knew about runs stale past their
heartbeat and about sessions pointing at a missing best run, and said nothing
about a session that simply never ended.
"""

from __future__ import annotations

import pytest

from hydromodpy.results.catalog import Catalog


@pytest.fixture
def catalog(tmp_path):
    cat = Catalog(tmp_path / "index.duckdb")
    try:
        yield cat
    finally:
        cat.close()


def _open_session(catalog: Catalog, session_id: str, *, minutes_ago: int) -> None:
    catalog._backend.execute(
        "INSERT INTO calibration_sessions "
        "(session_id, project, method, objective_name, n_iterations, config, started_at, "
        "status_id) "
        "VALUES (?, 'p', 'grid', 'nse', 0, '{}', "
        "current_timestamp - INTERVAL (?) MINUTE, "
        "(SELECT id FROM statuses WHERE code = 'running'))",
        [session_id, minutes_ago],
    )


def _status(catalog: Catalog, session_id: str) -> str:
    rows = catalog._backend.fetch_all(
        "SELECT st.code FROM calibration_sessions cs JOIN statuses st ON cs.status_id = st.id "
        "WHERE CAST(cs.session_id AS VARCHAR) = ?",
        [session_id],
    )
    return str(rows[0][0])


def test_a_session_still_running_past_the_window_is_listed(catalog) -> None:
    _open_session(catalog, "11111111-1111-1111-1111-111111111111", minutes_ago=600)

    found = catalog.sessions.abandoned(minutes=60)

    assert [entry["session_id"] for entry in found] == ["11111111-1111-1111-1111-111111111111"]
    assert found[0]["age_minutes"] >= 600


def test_a_session_inside_the_window_is_left_alone(catalog) -> None:
    """A calibration runs for hours; a young one is working, not abandoned."""
    _open_session(catalog, "22222222-2222-2222-2222-222222222222", minutes_ago=5)

    assert catalog.sessions.abandoned(minutes=60) == []


def test_a_finished_session_is_never_listed(catalog) -> None:
    _open_session(catalog, "33333333-3333-3333-3333-333333333333", minutes_ago=600)
    catalog.sessions.close_abandoned("33333333-3333-3333-3333-333333333333")

    assert catalog.sessions.abandoned(minutes=60) == []


def test_closing_one_marks_it_aborted_and_says_why(catalog) -> None:
    _open_session(catalog, "44444444-4444-4444-4444-444444444444", minutes_ago=600)

    catalog.sessions.close_abandoned("44444444-4444-4444-4444-444444444444")

    assert _status(catalog, "44444444-4444-4444-4444-444444444444") == "aborted"
    rows = catalog._backend.fetch_all(
        "SELECT error_message, ended_at FROM calibration_sessions "
        "WHERE CAST(session_id AS VARCHAR) = ?",
        ["44444444-4444-4444-4444-444444444444"],
    )
    assert "never closed" in str(rows[0][0])
    assert rows[0][1] is not None


def test_closing_a_session_that_is_not_running_changes_nothing(catalog) -> None:
    _open_session(catalog, "55555555-5555-5555-5555-555555555555", minutes_ago=600)
    catalog.sessions.close_abandoned("55555555-5555-5555-5555-555555555555")
    first = catalog._backend.fetch_all(
        "SELECT ended_at FROM calibration_sessions WHERE CAST(session_id AS VARCHAR) = ?",
        ["55555555-5555-5555-5555-555555555555"],
    )[0][0]

    catalog.sessions.close_abandoned("55555555-5555-5555-5555-555555555555")

    second = catalog._backend.fetch_all(
        "SELECT ended_at FROM calibration_sessions WHERE CAST(session_id AS VARCHAR) = ?",
        ["55555555-5555-5555-5555-555555555555"],
    )[0][0]
    assert first == second
