"""A calibration session read from its directory: trials, phases, config, best (D9).

``Session`` reads ``session.json``, ``trials.jsonl``, ``phases/`` and
``config.toml`` of ``sessions/<case>/`` and opens the run the best trial was
promoted to from its own directory. Nothing opens the index.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.session.view import TRIAL_COLUMNS, Session
from hydromodpy.results.storage.contract import SESSION_CONFIG_FILENAME
from tests._helpers.sealed_runs import make_project, seal_run, write_session_dir

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
    assert list(trials["iteration"]) == [1, 2, 3]
    assert set(trials["session_id"]) == {session_id}
    assert [phase.name for phase in session.phases] == ["steady_k", "transient"]
    assert session.config == {"calibration": {"method": "tpe"}}


def test_the_best_is_the_run_its_trial_was_promoted_to(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    sim_id = seal_run(project, "calage")
    write_session_dir(project, "calage", best_trial=2, best_sim_id=sim_id)

    best = Session(project / "sessions" / "calage").best

    assert best is not None
    assert best.sim_id == sim_id
    assert best.dir == (project / "runs" / "calage").resolve()


def test_no_best_while_no_run_holds_the_best_trial(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    write_session_dir(project, "searching", status="running")
    other = seal_run(project, "calage")
    write_session_dir(project, "calage", best_trial=2, best_sim_id=other[:-4] + "ffff")

    assert Session(project / "sessions" / "searching").best is None
    assert Session(project / "sessions" / "calage").best is None


def test_a_directory_without_a_descriptor_is_not_a_session(tmp_path: Path) -> None:
    (tmp_path / "sessions" / "loose").mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="not a calibration session"):
        Session(tmp_path / "sessions" / "loose")
