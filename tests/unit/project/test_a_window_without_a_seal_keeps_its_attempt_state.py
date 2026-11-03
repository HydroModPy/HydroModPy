"""A window that stops before the seal keeps ``<run>/.hmp/`` for the resume.

``--until run_solver`` ends the attempt ``completed`` without a manifest,
which reads as ``partial``. Its journal and checkpoints stay: the next
``--resume`` of the case claims attempt 2 in place and picks up from the
journal. Only the seal of a completed run removes the attempt state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.state.paths import INTERNAL_DIRNAME, RUN_INTERNAL_CHECKPOINTS_DIRNAME
from hydromodpy.results.outcome import effective_status, read_outcome
from hydromodpy.workflow.tracking.journal import WorkflowJournal
from tests.unit.project.test_run_pipeline_state import DEM, PROJECT_TOML

CASE = "asked_name"


class _JournallingPipeline:
    """A pipeline double that journals its first step for real and records what it was asked."""

    calls: list[dict] = []

    def __init__(self, steps, *, workspace, run_dir) -> None:
        self.steps = steps
        self.workspace = workspace
        self.run_dir = run_dir

    def run(
        self, state, *, resume_from=None, parallel=True, model_phase_ready=False, heartbeat=None
    ):
        type(self).calls.append({"resume_from": resume_from, "steps": len(self.steps)})
        if heartbeat is not None:
            heartbeat.set_step("validate")
        if resume_from is None:
            journal = WorkflowJournal(self.run_dir)
            step_id = journal.start_step(
                run_id=state.run_id, step_order=0, step_name="validate", inputs_hash="x"
            )
            journal.finish_step(step_id=step_id, status="completed")
        return state


def test_a_window_that_stops_before_the_seal_keeps_its_attempt_state_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hydromodpy.project.facade import Project

    config_path = tmp_path / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(root=tmp_path.as_posix(), dem=DEM.as_posix()), encoding="utf-8"
    )
    _JournallingPipeline.calls = []
    monkeypatch.setattr("hydromodpy.workflow.runner.Pipeline", _JournallingPipeline)
    monkeypatch.setenv("HMP_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("HMP_WORKSPACE", str(tmp_path))
    run_dir = tmp_path / "runs" / CASE

    with Project(config_path, no_display=True) as project:
        project._execute(name=CASE, until_step="run_solver")

    outcome = read_outcome(run_dir)
    assert outcome is not None and outcome.status == "completed" and outcome.attempt == 1
    assert effective_status(run_dir) == "partial", "completed without a seal is partial"
    checkpoints = run_dir / INTERNAL_DIRNAME / RUN_INTERNAL_CHECKPOINTS_DIRNAME
    assert (checkpoints / "steps.json").is_file(), "the journal survives a window without a seal"
    assert not (run_dir / "manifest.json").exists()

    with Project(config_path, no_display=True) as project:
        project._execute(resume=CASE, until_step="run_solver")

    resumed = read_outcome(run_dir)
    assert resumed is not None and resumed.attempt == 2
    assert (run_dir / "attempts" / "1" / "outcome.json").is_file()
    assert _JournallingPipeline.calls[-1]["resume_from"] == 1, "the resume picks up after step 0"
    assert (checkpoints / "steps.json").is_file()
    assert not (tmp_path / INTERNAL_DIRNAME / "index.duckdb").exists()
