"""A calibration session read from its directory: trials, phases, config, best (D9).

``Session`` reads ``session.json``, ``trials.jsonl``, ``phases/`` and
``config.toml`` of ``sessions/<case>/`` and opens the run the best trial was
promoted to from its own directory. Nothing opens the index.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.errors import SeveralCasesError
from hydromodpy.results.record.checks import CalibratedBy
from hydromodpy.results.session.descriptor import BestCase, BestTrial, write_session
from hydromodpy.results.session.journal import append_trial
from hydromodpy.results.session.view import PROFILE_COLUMNS, TRIAL_COLUMNS, Session
from hydromodpy.results.storage.contract import SESSION_CONFIG_FILENAME
from hydromodpy.results.storage.run_profile import ProfileLine
from tests._helpers.sealed_runs import make_project, seal_run, write_session_dir
from tests._helpers.session_documents import NOW, joint_session, joint_trial, trial_line

pytestmark = pytest.mark.fast


@pytest.fixture(autouse=True)
def _no_index(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args, **_kwargs):
        raise AssertionError("reading a session opened the index")

    monkeypatch.setattr(Catalog, "__init__", _refuse)


def test_a_session_reads_its_trials_phases_and_config(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    session_id = write_session_dir(project, "calage", trials=3, phases=("steady_k", "transient"))
    (project / "sessions" / "calage" / SESSION_CONFIG_FILENAME).write_text(
        '[calibration]\nmethod = "tpe"\n', encoding="utf-8"
    )

    session = Session(project / "sessions" / "calage")

    assert session.name == "calage"
    assert session.status == "completed"
    assert session.descriptor.session_id == session_id
    trials = session.trials
    assert list(trials.columns) == list(TRIAL_COLUMNS)
    assert list(trials["trial"]) == [1, 2, 3]
    assert set(trials["case_id"]) == {"calage"}
    assert set(trials["session_id"]) == {session_id}
    assert [phase.name for phase in session.phases] == ["steady_k", "transient"]
    assert session.config == {"calibration": {"method": "tpe"}}


def test_no_best_while_no_run_holds_the_best_trial(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    write_session_dir(project, "searching", status="running")
    other = seal_run(project, "calage")
    write_session_dir(project, "calage", best_trial=2, best_sim_id=other[:-4] + "ffff")

    assert Session(project / "sessions" / "searching").best is None
    assert Session(project / "sessions" / "calage").best is None


def test_a_paired_run_without_a_pointer_must_come_from_the_best_trial(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    session_id = write_session_dir(project, "calage", best_trial=2, best_sim_id=None)
    older = CalibratedBy(session_id=session_id, trial=1, session_status="completed")
    seal_run(project, "calage", calibrated_by=older)

    assert Session(project / "sessions" / "calage").best is None

    other = make_project(tmp_path / "q")
    session_id = write_session_dir(other, "calage", best_trial=2, best_sim_id=None)
    newer = CalibratedBy(session_id=session_id, trial=2, session_status="completed")
    sim_id = seal_run(other, "calage", calibrated_by=newer)

    best = Session(other / "sessions" / "calage").best
    assert best is not None and best.sim_id == sim_id


def test_a_directory_without_a_descriptor_is_not_a_session(tmp_path: Path) -> None:
    (tmp_path / "sessions" / "loose").mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="not a calibration session"):
        Session(tmp_path / "sessions" / "loose")


def test_a_session_of_several_cases_reads_one_row_per_trial_and_case(tmp_path: Path) -> None:
    directory = tmp_path / "sessions" / "joint"
    directory.mkdir(parents=True)
    write_session(
        directory, joint_session(best=BestTrial(trial=1, cost=0.4, parameters={"K": 2e-5}))
    )
    append_trial(directory, joint_trial())

    session = Session(directory)
    trials = session.trials

    assert (session.cases, session.sites) == (("a", "b"), ("S1", "S2"))
    assert session.windows["calibration"].of("b").start.isoformat() == "2015-01-01"
    assert list(trials[["trial", "case_id", "site", "case_cost"]].itertuples(index=False)) == [
        (1, "a", "S1", 0.3),
        (1, "b", "S2", 0.5),
    ]
    assert set(trials["cost"]) == {0.4}
    assert (session.best_cost, session.best_parameters) == (0.4, {"K": 2e-5})
    assert session.best_by_case == {}


def test_the_best_of_several_cases_is_refused_and_best_by_case_names_each(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    sim_id = seal_run(project, "a")
    directory = project / "sessions" / "joint"
    directory.mkdir(parents=True)
    best = BestTrial(
        trial=1,
        cost=0.4,
        cases={"a": BestCase(sim_id=sim_id, rel_dir="runs/a", cost=0.3), "b": BestCase(cost=0.5)},
    )
    write_session(directory, joint_session(best=best, started_at=NOW))

    session = Session(directory)

    with pytest.raises(SeveralCasesError, match="best_by_case"):
        _ = session.best
    by_case = session.best_by_case
    assert by_case["a"] is not None and by_case["a"].sim_id == sim_id
    assert by_case["b"] is None


def _line(kind: str, name: str, seconds: float, reused: str = "no") -> ProfileLine:
    return ProfileLine(
        kind=kind, name=name, attempt=1, started_at=NOW, duration_s=seconds, reused=reused
    )


def _journal(tmp_path: Path) -> Path:
    directory = tmp_path / "sessions" / "calage"
    directory.mkdir(parents=True)
    write_session(directory, joint_session())
    # Trial 1 is proposed, finished and linked, trial 2 finished with a rerun, trial 3 only proposed.
    append_trial(directory, trial_line(1, event="proposed", cost=None, status="running", batch=1))
    append_trial(directory, trial_line(2, event="proposed", cost=None, status="running", batch=1))
    append_trial(directory, trial_line(3, event="proposed", cost=None, status="running", batch=2))
    append_trial(
        directory,
        trial_line(
            1,
            batch=1,
            rule="2",
            window="calibration",
            profile=[
                _line("step", "run_solver", 3.0),
                _line("solve", "run", 2.5),
            ],
        ),
    )
    append_trial(
        directory,
        trial_line(
            2,
            batch=1,
            rule="2",
            window="calibration",
            profile=[
                _line("step", "run_solver", 1.0),
                _line("solve", "run", 0.5, "rerun"),
            ],
        ),
    )
    append_trial(
        directory,
        trial_line(
            1,
            event="linked",
            batch=1,
            rule="2",
            window="calibration",
            sim_id="x" * 12,
            profile=[_line("step", "run_solver", 3.0), _line("solve", "run", 2.5)],
        ),
    )
    return directory


def test_the_trial_frame_counts_folded_trials_and_reads_the_new_columns(tmp_path: Path) -> None:
    session = Session(_journal(tmp_path))

    trials = session.trials.set_index("trial")

    assert list(trials.index) == [1, 2, 3]
    assert list(trials["batch"]) == [1, 1, 2]
    assert list(trials.loc[[1, 2], "rule"]) == ["2", "2"]
    assert list(trials.loc[[1, 2], "window"]) == ["calibration", "calibration"]
    assert list(trials.loc[[1, 2], "solve_s"]) == [2.5, 0.5]
    assert list(trials.loc[[1, 2], "reused"]) == ["no", "rerun"]
    assert trials.loc[3, "status"] == "running"
    assert trials.loc[3, ["rule", "window", "solve_s", "reused"]].isna().all()


def test_the_profile_adds_the_lines_of_the_last_line_of_each_trial(tmp_path: Path) -> None:
    profile = Session(_journal(tmp_path)).profile()

    assert list(profile.columns) == list(PROFILE_COLUMNS)
    rows = {
        (row.kind, row.name, row.reused): (row.lines, row.duration_s)
        for row in profile.itertuples(index=False)
    }
    assert rows == {
        ("solve", "run", "no"): (1, 2.5),
        ("solve", "run", "rerun"): (1, 0.5),
        ("step", "run_solver", "no"): (2, 4.0),
    }
