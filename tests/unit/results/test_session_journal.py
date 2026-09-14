"""A calibration session survives the index: written live, read back on rebuild."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from hydromodpy.core.state.paths import catalog_path_for
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.reindex import rebuild_index
from hydromodpy.results.session_journal import (
    SessionJournal,
    SessionTrial,
    read_descriptor,
    read_trials,
    session_dirs_for,
    sessions_dir_for,
)
from hydromodpy.results.storage.contract import (
    SESSION_DESCRIPTOR_FILENAME,
    SESSION_TRIALS_FILENAME,
)

SEARCH_SPACE = {
    "K_aquifer": {
        "bounds": [1e-6, 1e-3],
        "transform": "log",
        "target": "flow.param.K.field.value",
        "units": "m/s",
    }
}


def _trial(number: int, objective: float, **kwargs) -> SessionTrial:
    """One completed trial of the synthetic session."""
    return SessionTrial(
        trial=number,
        parameters={"K_aquifer": {"value": 1e-4 * (number + 1)}},
        objective_value=objective,
        status="completed",
        duration_s=0.5 + number,
        metrics={"rmse": objective},
        params_hash=f"v2:{number:064x}",
        **kwargs,
    )


def _start(project_root, session_id: str) -> SessionJournal:
    """Open a journal for one session of the synthetic project."""
    return SessionJournal.start(
        project_root,
        session_id=session_id,
        project="demo",
        method="optuna",
        objective_name="rmse",
        search_space=SEARCH_SPACE,
        config={"method": "optuna", "variable": "head", "max_iter": 3},
        started_at=datetime.now(UTC),
    )


@pytest.fixture
def session_id() -> str:
    return uuid.uuid4().hex


@pytest.fixture
def project(tmp_path, session_id):
    """A project whose only content is one finished calibration session."""
    root = tmp_path / "demo"
    root.mkdir()
    journal = _start(root, session_id)
    for number, objective in enumerate((0.42, 0.19, 0.31)):
        journal.append(_trial(number, objective))
    journal.finish(
        status="completed",
        duration_s=3.7,
        ended_at=datetime.now(UTC),
        best_trial=1,
        best_objective=0.19,
    )
    return root


# -- what the journal writes, while it writes it ----------------------------


def test_the_session_directory_holds_the_descriptor_and_the_trials(project, session_id):
    directory = session_dirs_for(project)[0]

    assert directory.parent == sessions_dir_for(project)
    assert (directory / SESSION_DESCRIPTOR_FILENAME).is_file()
    assert (directory / SESSION_TRIALS_FILENAME).is_file()
    assert directory.name.endswith(f"-optuna-{session_id[:8]}")


def test_the_descriptor_carries_identity_search_space_objective_and_best_trial(project, session_id):
    descriptor = read_descriptor(session_dirs_for(project)[0])

    assert descriptor.session_id == session_id
    assert descriptor.project == "demo"
    assert descriptor.method == "optuna"
    assert descriptor.objective_name == "rmse"
    assert descriptor.search_space == SEARCH_SPACE
    assert descriptor.config["variable"] == "head"
    assert descriptor.started_at < descriptor.ended_at
    assert descriptor.status == "completed"
    assert (descriptor.best_trial, descriptor.best_objective) == (1, 0.19)


def test_one_line_per_trial_carries_the_whole_trial(project):
    trials = read_trials(session_dirs_for(project)[0])

    assert [t.trial for t in trials] == [0, 1, 2]
    assert [t.objective_value for t in trials] == [0.42, 0.19, 0.31]
    assert [t.status for t in trials] == ["completed"] * 3
    assert [t.from_cache for t in trials] == [False] * 3
    assert trials[1].parameters == {"K_aquifer": {"value": 2e-4}}
    assert trials[1].metrics == {"rmse": 0.19}
    assert trials[1].duration_s == 1.5


def test_an_interrupted_session_keeps_the_trials_it_had_time_to_run(tmp_path, session_id):
    root = tmp_path / "demo"
    root.mkdir()
    journal = _start(root, session_id)
    journal.append(_trial(0, 0.42))

    descriptor = read_descriptor(journal.directory)

    assert descriptor.status == "running"
    assert descriptor.ended_at is None
    assert [t.trial for t in read_trials(journal.directory)] == [0]


def test_a_trial_written_twice_keeps_its_last_write(tmp_path, session_id):
    root = tmp_path / "demo"
    root.mkdir()
    journal = _start(root, session_id)
    journal.append(_trial(0, 0.42))
    journal.append(_trial(0, 0.11, sim_id=str(uuid.uuid4())))

    trials = read_trials(journal.directory)

    assert [(t.trial, t.objective_value) for t in trials] == [(0, 0.11)]


def test_a_directory_without_a_descriptor_is_not_a_calibration_session(project):
    (sessions_dir_for(project) / "spinup-2026").mkdir()

    assert len(session_dirs_for(project)) == 1


# -- what the rebuild gives back --------------------------------------------


def _session_row(project_root) -> dict:
    with Catalog(project_root, read_only=True) as catalog:
        row = catalog.backend.fetch_one(
            """SELECT CAST(s.session_id AS VARCHAR), s.project, s.method, s.objective_name,
                      s.n_iterations, s.best_objective, st.code, s.duration_s, s.config
                 FROM calibration_sessions s
                 LEFT JOIN statuses st ON st.id = s.status_id"""
        )
    keys = (
        "session_id",
        "project",
        "method",
        "objective_name",
        "n_iterations",
        "best_objective",
        "status",
        "duration_s",
        "config",
    )
    return dict(zip(keys, row, strict=True))


def test_the_rebuild_puts_the_session_back_in_the_index(project, session_id):
    report = rebuild_index(project)

    assert report.sessions == (session_dirs_for(project)[0].name,)
    assert report.rows["calibration_sessions"] == 1
    assert report.rows["calibration_iterations"] == 3
    row = _session_row(project)
    assert uuid.UUID(row["session_id"]).hex == session_id
    assert row["project"] == "demo"
    assert row["method"] == "optuna"
    assert row["objective_name"] == "rmse"
    assert row["n_iterations"] == 3
    assert row["best_objective"] == pytest.approx(0.19)
    assert row["status"] == "completed"
    assert json.loads(row["config"])["variable"] == "head"


def test_the_rebuild_puts_every_trial_back_in_the_index(project, session_id):
    rebuild_index(project)

    with Catalog(project, read_only=True) as catalog:
        rows = catalog.backend.fetch_all(
            "SELECT iteration, objective_value, status, parameters, metrics, duration_s "
            "FROM calibration_iterations ORDER BY iteration"
        )
    assert [row[0] for row in rows] == [0, 1, 2]
    assert [row[1] for row in rows] == pytest.approx([0.42, 0.19, 0.31])
    assert {row[2] for row in rows} == {"completed"}
    assert json.loads(rows[1][3]) == {"K_aquifer": {"value": 2e-4}}
    assert json.loads(rows[1][4]) == {"rmse": 0.19}


def test_the_calibration_report_finds_its_session_again(project, session_id):
    from hydromodpy.calibration.report import (
        load_session_report_data,
        resolve_calibration_session_id,
    )

    catalog_path_for(project).unlink(missing_ok=True)
    rebuild_index(project)

    with Catalog(project, read_only=True) as catalog:
        resolved = resolve_calibration_session_id(catalog, None)
        data = load_session_report_data(
            catalog=catalog, session_id=resolved, workspace_root=project
        )
    assert resolved == session_id
    assert data.session["method"] == "optuna"
    assert len(data.iterations) == 3
    assert data.variable == "head"
    # The report names the session exactly as the disk does: no second
    # vocabulary, no opaque 32-character identifier.
    assert data.session_name == session_dirs_for(project)[0].name


def test_an_interrupted_session_is_indexed_with_the_trials_on_disk(tmp_path, session_id):
    root = tmp_path / "demo"
    root.mkdir()
    journal = _start(root, session_id)
    journal.append(_trial(0, 0.42))
    journal.append(_trial(1, 0.19))

    rebuild_index(root)

    row = _session_row(root)
    assert row["status"] == "running"
    assert row["n_iterations"] == 2


def test_two_rebuilds_describe_the_same_calibration(project):
    rebuild_index(project)
    first = _session_row(project)

    rebuild_index(project)

    with Catalog(project, read_only=True) as catalog:
        assert catalog.backend.fetch_one("SELECT COUNT(*) FROM calibration_sessions")[0] == 1
        assert catalog.backend.fetch_one("SELECT COUNT(*) FROM calibration_iterations")[0] == 3
    assert _session_row(project) == first


def test_a_malformed_descriptor_is_reported_and_left_out(project):
    directory = session_dirs_for(project)[0]
    (directory / SESSION_DESCRIPTOR_FILENAME).write_text('{"project": "demo"}')

    report = rebuild_index(project)

    assert report.sessions == ()
    assert [item.run for item in report.skipped] == [directory.name]
    assert "session_id" in report.skipped[0].reason
