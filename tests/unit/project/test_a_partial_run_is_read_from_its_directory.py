"""``Project.simulate(until_step=...)`` returns a view of the partial run.

A window that stops before the seal ends ``completed`` without a manifest,
which reads as ``partial``. The index lists sealed runs only, so the view of
that run reads its own directory instead of asking the index for it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.state.paths import PROJECT_MARKER_FILENAME
from hydromodpy.project.attempt import run_attempt, sealed_run_of
from hydromodpy.project.runner import ProjectRunner
from hydromodpy.results.outcome import effective_status
from hydromodpy.results.storage.run_store import RunStore
from tests._helpers.run_stores import facts_of

CASE = "until_extract"


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "demo"
    project.mkdir()
    (project / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    return project


def _runner_of(project: Path, monkeypatch: pytest.MonkeyPatch, *, write_facts: bool):
    """Return a runner whose ``execute`` closes a partial attempt of *CASE*."""
    with run_attempt(project, CASE, case_id=CASE, project="demo", site=None) as handle:
        if write_facts:
            facts = facts_of(handle.claim, project="demo", n_cells=4, n_layers=1)
            RunStore.open(handle.run_dir, facts=facts, workspace=project).close()
    sealed = sealed_run_of(handle.claim, project)
    owner = SimpleNamespace(_store=None, _run_history=[])
    runner = ProjectRunner(owner)
    monkeypatch.setattr(runner, "execute", lambda **_: sealed)
    monkeypatch.setattr("hydromodpy.project.phases.open_catalog", lambda _project: None)
    return runner, owner, sealed


def test_a_partial_run_is_read_from_its_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    runner, owner, sealed = _runner_of(project, monkeypatch, write_facts=True)

    assert effective_status(sealed.run_dir) == "partial"
    run = runner.run(until_step="extract")

    assert run is not None
    assert run.sim_id == sealed.sim_id
    assert run.name == CASE
    assert run.status == "partial"
    assert owner._run_history == [run]


def test_a_partial_run_without_facts_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    runner, owner, _ = _runner_of(project, monkeypatch, write_facts=False)

    assert runner.run(until_step="extract") is None
    assert owner._run_history == []
