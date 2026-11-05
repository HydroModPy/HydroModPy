"""End-to-end resume test using a minimal in-memory pipeline.

Drives :class:`Pipeline` against a run directory of a fresh project. A first
run crashes on step 3, a second run reads the step journal under
``<run>/.hmp/checkpoints/`` to resume from step 3 onwards. The test also
verifies that the pulse the caller starts names the step under way and stays
fresh during the run, and that an attempt whose pulse stopped reads stale.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import StepError
from hydromodpy.core.state.result_dirs import run_dir_rel
from hydromodpy.results.heartbeat import HeartbeatThread, read_heartbeat
from hydromodpy.results.outcome import DEFAULT_STALE_AFTER_S, effective_status
from hydromodpy.workflow.record.journal import WorkflowJournal
from hydromodpy.workflow.record.resume import ResumePlanner
from hydromodpy.workflow.runner import Pipeline
from tests._helpers.sealed_runs import make_project, write_attempt


class _ArtifactStep:
    """Pipeline step that writes a tagged file under the workspace."""

    def __init__(self, name: str, payload: str | None = None, fail: bool = False) -> None:
        self.name = name
        self._payload = payload if payload is not None else name
        self._fail = bool(fail)

    def run(self, state):
        if self._fail:
            raise RuntimeError(f"simulated crash on {self.name}")
        from hydromodpy.workflow.state import PipelineState as _PS

        assert isinstance(state, _PS)
        workspace = Path(state.get("workspace"))
        artefact = workspace / "artefacts" / f"{self.name}.txt"
        artefact.parent.mkdir(parents=True, exist_ok=True)
        artefact.write_text(self._payload, encoding="utf-8")
        completed = list(state.get("completed", []))
        completed.append(self.name)
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            completed=completed,
        )

    def artifacts(self, state) -> tuple[str, ...]:
        return (f"artefacts/{self.name}.txt",)


def _run_dir(workspace: Path, run_id: str) -> Path:
    """Create the project and ``runs/<run_id>``; return the run directory."""
    make_project(workspace)
    directory = workspace / run_dir_rel(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _initial_state(workspace: Path, run_id: str):
    from hydromodpy.workflow.state import PipelineState

    return PipelineState(run_id=run_id, data={"workspace": str(workspace), "completed": []})


@pytest.mark.integration
def test_crash_then_resume_skips_completed_prefix(tmp_path: Path) -> None:
    workspace = tmp_path
    run_dir = _run_dir(workspace, "run-A")

    blueprint = (
        _ArtifactStep("step0"),
        _ArtifactStep("step1"),
        _ArtifactStep("step2", fail=True),
        _ArtifactStep("step3"),
        _ArtifactStep("step4"),
    )
    pipeline = Pipeline(blueprint, workspace=workspace, run_dir=run_dir)
    with pytest.raises(StepError):
        pipeline.run(_initial_state(workspace, "run-A"))

    journal = WorkflowJournal(run_dir)
    rows = journal.list_steps("run-A")
    statuses = [(r.step_order, r.step_name, r.status) for r in rows]
    assert statuses[:2] == [(0, "step0", "completed"), (1, "step1", "completed")]
    assert statuses[2] == (2, "step2", "failed")

    plan = ResumePlanner(journal, workspace).compute(
        run_id="run-A",
        current_config_sha256=None,
        steps_blueprint=tuple(s.name for s in blueprint),
    )
    assert plan.restart_index == 2
    assert plan.last_completed is not None
    assert plan.last_completed.step_name == "step1"

    recovery_blueprint = (
        _ArtifactStep("step0"),
        _ArtifactStep("step1"),
        _ArtifactStep("step2"),
        _ArtifactStep("step3"),
        _ArtifactStep("step4"),
    )
    pipeline = Pipeline(recovery_blueprint, workspace=workspace, run_dir=run_dir)
    final = pipeline.run(_initial_state(workspace, "run-A"), resume_from=2)
    assert final.get("completed") == ["step2", "step3", "step4"]

    statuses = [r.status for r in WorkflowJournal(run_dir).list_steps("run-A")]
    assert statuses == ["completed", "completed", "completed", "completed", "completed"]

    for name in ("step0", "step1", "step2", "step3", "step4"):
        assert (workspace / "artefacts" / f"{name}.txt").is_file()


@pytest.mark.integration
def test_heartbeat_keeps_sim_fresh_during_run(tmp_path: Path) -> None:
    """The pulse the caller starts names the step under way and stays fresh."""
    workspace = tmp_path
    run_dir = _run_dir(workspace, "run-B")
    attempt_id = uuid.uuid4().hex

    blueprint = (
        _ArtifactStep("step0"),
        _ArtifactStep("step1"),
        _ArtifactStep("step2"),
    )
    pipeline = Pipeline(blueprint, workspace=workspace, run_dir=run_dir)
    with HeartbeatThread(run_dir, attempt_id=attempt_id, interval_s=60.0) as heartbeat:
        pipeline.run(_initial_state(workspace, "run-B"), heartbeat=heartbeat)

    beat = read_heartbeat(run_dir)
    assert beat is not None
    assert beat.attempt_id == attempt_id
    assert beat.step == "step2"
    assert (datetime.now(UTC) - beat.at).total_seconds() < 60.0


@pytest.mark.integration
def test_simulated_hard_crash_leaves_stale_heartbeat(tmp_path: Path) -> None:
    """A run that dies without writing a final status reads stale once its pulse is old."""
    project = make_project(tmp_path)
    run_dir = write_attempt(
        project,
        run_dir_rel("x"),
        status="running",
        heartbeat_age_s=30 * 60,
    )

    assert effective_status(run_dir) == "stale"
    assert effective_status(run_dir, now=datetime.now(UTC) - timedelta(minutes=30)) == "running"
    assert DEFAULT_STALE_AFTER_S < 30 * 60


@pytest.mark.integration
def test_artifact_deletion_triggers_partial_redo(tmp_path: Path) -> None:
    """Deleting a downstream artifact reruns the affected steps only."""
    workspace = tmp_path
    run_dir = _run_dir(workspace, "run-C")

    blueprint = (
        _ArtifactStep("alpha"),
        _ArtifactStep("beta"),
        _ArtifactStep("gamma"),
    )
    pipeline = Pipeline(blueprint, workspace=workspace, run_dir=run_dir)
    pipeline.run(_initial_state(workspace, "run-C"))

    (workspace / "artefacts" / "beta.txt").unlink()

    plan = ResumePlanner(WorkflowJournal(run_dir), workspace).compute(
        run_id="run-C",
        current_config_sha256=None,
        steps_blueprint=tuple(s.name for s in blueprint),
    )
    assert plan.restart_index == 1
    assert plan.last_completed is not None
    assert plan.last_completed.step_name == "alpha"

    # The journal keys steps on (run_id, step_order) and orders by step_order,
    # so resume is independent of wall-clock timing. No sleep needed.
    recovery = (
        _ArtifactStep("alpha"),
        _ArtifactStep("beta"),
        _ArtifactStep("gamma"),
    )
    pipeline = Pipeline(recovery, workspace=workspace, run_dir=run_dir)
    final = pipeline.run(_initial_state(workspace, "run-C"), resume_from=1)
    assert final.get("completed") == ["beta", "gamma"]

    rows = WorkflowJournal(run_dir).list_steps("run-C")
    assert [r.status for r in rows] == ["completed", "completed", "completed"]
