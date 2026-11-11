"""The project ``.hmp/`` is strictly rebuildable: delete it, reindex, nothing is missing.

``rm -rf <project>/.hmp`` followed by ``hmp catalog reindex`` must give back
the same project: the same cases under the same directories, with the same
status, label, parameters and metrics, and not one file outside ``.hmp/``
touched. State that cannot be rebuilt (the trash, the attempts, the launch
journals, the plans) lives in visible folders, never under ``.hmp/``.
"""

from __future__ import annotations

import hashlib
import importlib
import shutil
import sys
from pathlib import Path

import pytest

from hydromodpy.core.state.layout import INTERNAL_DIRNAME, catalog_path_for, internal_dir
from hydromodpy.results.catalog.facade import Catalog
from tests._helpers.sealed_runs import make_project, seal_run, write_attempt, write_session_dir

_CASE_STATE_SQL = (
    "SELECT rel_dir, kind, case_id, site, CAST(sim_id AS VARCHAR), attempt_id, status, "
    "name, solver, solution_key, label, rule_version, nse, n_samples, metric_rule_version "
    "FROM v_cases"
)
_PARAMETER_STATE_SQL = (
    "SELECT s.rel_dir, p.param_name, p.zone_id, p.value, p.origin, p.calibrated "
    "FROM parameters p JOIN simulations s ON s.sim_id = p.sim_id"
)
_METRIC_STATE_SQL = (
    "SELECT s.rel_dir, m.station_id, m.variable, m.metric, m.value, m.n_samples "
    "FROM metrics m JOIN simulations s ON s.sim_id = m.sim_id"
)
_SESSION_STATE_SQL = (
    "SELECT s.rel_dir, s.session_id, s.case_id, s.n_trials, s.best_trial, c.best_rel_dir, "
    "c.best_sim_id, s.status FROM calibration_sessions s "
    "JOIN calibration_session_cases c ON c.session_id = s.session_id AND c.case_id = s.case_id"
)
_TRIAL_STATE_SQL = (
    "SELECT i.session_id, i.trial, i.phase, i.cost, t.case_id, t.sim_id, t.rel_dir "
    "FROM calibration_iterations i "
    "JOIN calibration_trial_cases t ON t.session_id = i.session_id AND t.trial = i.trial"
)


def _reindex(monkeypatch, project: Path) -> int:
    module = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", ["hmp", "catalog", "reindex", "--workspace", str(project)])
    try:
        module.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _index_state(project: Path) -> dict[str, list[tuple]]:
    with Catalog(project) as catalog:
        return {
            query: sorted(tuple(row) for row in catalog.backend.fetch_all(query))
            for query in (
                _CASE_STATE_SQL,
                _PARAMETER_STATE_SQL,
                _METRIC_STATE_SQL,
                _SESSION_STATE_SQL,
                _TRIAL_STATE_SQL,
            )
        }


def _files_outside_internal(project: Path) -> dict[str, str]:
    """Relative path -> sha256 of every file outside the project ``.hmp/``."""
    return {
        path.relative_to(project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(project.rglob("*"))
        if path.is_file() and path.relative_to(project).parts[0] != INTERNAL_DIRNAME
    }


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    """Two versions of a run, a failed attempt, a session with its kept trial, indexed once."""
    root = make_project(tmp_path / "demo")
    seal_run(root, "nancon_monthly", nse=0.71, parameters={"K": 1e-5})
    seal_run(root, "nancon_monthly.v2", nse=0.64, parameters={"K": 2e-5})
    write_attempt(root, "runs/nancon_daily", status="failed")
    promoted = seal_run(root, "calibration", nse=0.8)
    seal_run(root, "calibration_t1", rel_dir="sessions/calibration/trials/0001")
    write_session_dir(
        root, "calibration", best_trial=1, best_sim_id=promoted, best_rel_dir="runs/calibration"
    )
    assert _reindex(monkeypatch, root) == 0
    return root


def test_deleting_the_internal_directory_loses_nothing(project, monkeypatch):
    state = _index_state(project)
    files = _files_outside_internal(project)
    assert len(state[_CASE_STATE_SQL]) == 6
    assert len(state[_SESSION_STATE_SQL]) == 1 and state[_TRIAL_STATE_SQL]

    shutil.rmtree(internal_dir(project))
    assert _reindex(monkeypatch, project) == 0

    assert catalog_path_for(project).is_file()
    assert _index_state(project) == state
    assert _files_outside_internal(project) == files


def test_the_rebuilt_index_names_each_case_by_its_directory(project, monkeypatch):
    shutil.rmtree(internal_dir(project))

    assert _reindex(monkeypatch, project) == 0

    rel_dirs = sorted(row[0] for row in _index_state(project)[_CASE_STATE_SQL])
    assert rel_dirs == [
        "runs/calibration",
        "runs/nancon_daily",
        "runs/nancon_monthly",
        "runs/nancon_monthly.v2",
        "sessions/calibration",
        "sessions/calibration/trials/0001",
    ]
    with Catalog(project) as catalog:
        versions = dict(catalog.backend.fetch_all("SELECT name, version_int FROM simulations"))
    assert versions["nancon_monthly"] == 1
    assert versions["nancon_monthly.v2"] == 2
