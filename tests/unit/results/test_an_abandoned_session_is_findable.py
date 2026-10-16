"""A calibration that never closed has to be findable.

A session is opened ``running`` and closed in a ``finally``. A SIGKILL, a
power cut or a lost machine runs neither, so its ``session.json`` stays
``running`` for good. The project watchers count such a session from its
descriptor, without the index, and the index shows it as the disk has it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hydromodpy.cli._workers.catalog import (
    ABANDONED_SESSION_MINUTES,
    abandoned_calibration_session_count,
)
from hydromodpy.results.catalog import Catalog, rebuild_index
from tests._helpers.sealed_runs import make_project, write_session_dir

LONG_AGO = datetime.now(UTC) - timedelta(minutes=ABANDONED_SESSION_MINUTES + 60)


def test_a_session_still_running_past_the_window_is_counted(tmp_path) -> None:
    root = make_project(tmp_path / "demo")
    write_session_dir(root, "lost", status="running", started_at=LONG_AGO)

    assert abandoned_calibration_session_count(root) == 1


def test_a_session_inside_the_window_is_left_alone(tmp_path) -> None:
    """A calibration runs for hours; a young one is working, not abandoned."""
    root = make_project(tmp_path / "demo")
    write_session_dir(root, "young", status="running", started_at=datetime.now(UTC))

    assert abandoned_calibration_session_count(root) == 0


def test_a_finished_session_is_never_counted(tmp_path) -> None:
    root = make_project(tmp_path / "demo")
    write_session_dir(root, "done", status="completed", started_at=LONG_AGO)
    write_session_dir(root, "broken", status="failed", started_at=LONG_AGO)

    assert abandoned_calibration_session_count(root) == 0


def test_the_index_lists_the_lost_session_as_running(tmp_path) -> None:
    root = make_project(tmp_path / "demo")
    write_session_dir(root, "lost", session_id="lost0001", status="running", started_at=LONG_AGO)

    rebuild_index(root)

    with Catalog(root) as catalog:
        sessions = catalog.backend.fetch_all(
            "SELECT session_id, status, ended_at FROM calibration_sessions"
        )
        cases = catalog.cases
    assert [tuple(row) for row in sessions] == [("lost0001", "running", None)]
    assert cases.loc[cases["rel_dir"] == "sessions/lost", "status"].item() == "running"
