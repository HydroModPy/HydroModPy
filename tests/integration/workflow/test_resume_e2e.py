"""End-to-end resume test using a minimal in-memory pipeline.

Drives :class:`Pipeline` against a fresh workspace + catalog. A first run
crashes on step 3, a second run consults the workflow journal to resume
from step 3 onwards. The test also verifies that the heartbeat thread keeps
``v_workflow_heartbeats`` fresh during the run, and that a hard-crash leaves
a stale event-stream heartbeat visible to ``hmp catalog gc``.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import StepError
from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.workflow.journal import WorkflowJournal
from hydromodpy.workflow.resume import ResumePlanner
from hydromodpy.workflow.runner import Pipeline

SIM_ID = "55555555-5555-5555-5555-555555555555"


class _ArtifactStep:
    """Pipeline step that writes a tagged file under the workspace."""

    def __init__(self, name: str, payload: str | None = None, fail: bool = False) -> None:
        self.name = name
        self._payload = payload if payload is not None else name
        self._fail = bool(fail)

    def run(self, state):
        if self._fail:
            raise RuntimeError(f"simulated crash on {self.name}")
        from hydromodpy.workflow.internals.state import PipelineState as _PS

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


def _register_running_sim(catalog: SimulationCatalog, sim_id: str) -> None:
    catalog.connection.execute(
        """
        INSERT INTO simulations
            (sim_id, project, solver_id, status_id,
             zarr_path, storage_basename)
        VALUES (?, 'p1',
                (SELECT id FROM solvers WHERE code = 'modflow6'),
                (SELECT id FROM statuses WHERE code = 'running'),
                ?, ?)
        """,
        [sim_id, "simulations/x.zarr", "x"],
    )


def _initial_state(workspace: Path, run_id: str, sim_id: str | None = None):
    from hydromodpy.workflow.internals.state import PipelineState

    payload = {"workspace": str(workspace), "completed": []}
    if sim_id is not None:
        payload["sim_id"] = sim_id
    return PipelineState(run_id=run_id, data=payload)


@pytest.mark.integration
def test_crash_then_resume_skips_completed_prefix(tmp_path: Path) -> None:
    workspace = tmp_path
    SimulationCatalog(workspace).close()

    blueprint = (
        _ArtifactStep("step0"),
        _ArtifactStep("step1"),
        _ArtifactStep("step2", fail=True),
        _ArtifactStep("step3"),
        _ArtifactStep("step4"),
    )
    pipeline = Pipeline(blueprint, workspace=workspace)
    with pytest.raises(StepError):
        pipeline.run(_initial_state(workspace, "run-A"))

    catalog = SimulationCatalog(workspace)
    try:
        journal = WorkflowJournal(catalog)
        rows = journal.list_steps("run-A")
        statuses = [(r.step_order, r.step_name, r.status) for r in rows]
        assert statuses[:2] == [(0, "step0", "completed"), (1, "step1", "completed")]
        assert statuses[2] == (2, "step2", "failed")

        planner = ResumePlanner(journal, workspace)
        plan = planner.compute(
            run_id="run-A",
            current_config_sha256=None,
            steps_blueprint=tuple(s.name for s in blueprint),
        )
        assert plan.restart_index == 2
        assert plan.last_completed is not None
        assert plan.last_completed.step_name == "step1"
    finally:
        catalog.close()

    recovery_blueprint = (
        _ArtifactStep("step0"),
        _ArtifactStep("step1"),
        _ArtifactStep("step2"),
        _ArtifactStep("step3"),
        _ArtifactStep("step4"),
    )
    pipeline = Pipeline(recovery_blueprint, workspace=workspace)
    final = pipeline.run(_initial_state(workspace, "run-A"), resume_from=2)
    completed = final.get("completed")
    assert completed == ["step2", "step3", "step4"]

    catalog = SimulationCatalog(workspace)
    try:
        journal = WorkflowJournal(catalog)
        rows = journal.list_steps("run-A")
        statuses = [r.status for r in rows]
        assert statuses == ["completed", "completed", "completed", "completed", "completed"]
    finally:
        catalog.close()

    for name in ("step0", "step1", "step2", "step3", "step4"):
        assert (workspace / "artefacts" / f"{name}.txt").is_file()


@pytest.mark.integration
def test_heartbeat_keeps_sim_fresh_during_run(tmp_path: Path) -> None:
    workspace = tmp_path
    catalog = SimulationCatalog(workspace)
    try:
        _register_running_sim(catalog, SIM_ID)
    finally:
        catalog.close()

    blueprint = (
        _ArtifactStep("step0"),
        _ArtifactStep("step1"),
        _ArtifactStep("step2"),
    )
    pipeline = Pipeline(blueprint, workspace=workspace)
    pipeline.run(_initial_state(workspace, "run-B", sim_id=SIM_ID))

    catalog = SimulationCatalog(workspace)
    try:
        row = catalog.connection.execute(
            "SELECT last_heartbeat FROM v_workflow_heartbeats WHERE run_id = ?",
            [SIM_ID],
        ).fetchone()
        assert row is not None and row[0] is not None
        last_hb = row[0]
        if last_hb.tzinfo is None:
            last_hb = last_hb.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        assert (now - last_hb).total_seconds() < 60.0
    finally:
        catalog.close()


@pytest.mark.integration
def test_simulated_hard_crash_leaves_stale_heartbeat(tmp_path: Path) -> None:
    """A run that dies without writing a final status leaves the sim stale."""
    workspace = tmp_path
    catalog = SimulationCatalog(workspace)
    try:
        _register_running_sim(catalog, SIM_ID)
        catalog.connection.execute(
            """
            INSERT INTO workflow_events (run_id, step_name, event_type, ts)
            VALUES (?, 'pipeline', 'heartbeat', ?)
            """,
            [SIM_ID, datetime.now(UTC) - timedelta(minutes=30)],
        )
    finally:
        catalog.close()

    catalog = SimulationCatalog(workspace)
    try:
        cutoff = datetime.now(UTC) - timedelta(minutes=10)
        row = catalog.connection.execute(
            """
            SELECT sim_id FROM simulations s
              JOIN statuses st ON s.status_id = st.id
         LEFT JOIN v_workflow_heartbeats wh ON wh.run_id = s.sim_id
             WHERE st.code = 'running'
               AND (wh.last_heartbeat IS NULL OR wh.last_heartbeat < ?)
            """,
            [cutoff],
        ).fetchone()
        assert row is not None and str(row[0]) == SIM_ID
    finally:
        catalog.close()


@pytest.mark.integration
def test_artifact_deletion_triggers_partial_redo(tmp_path: Path) -> None:
    """Deleting a downstream artefact reruns the affected steps only."""
    workspace = tmp_path
    SimulationCatalog(workspace).close()

    blueprint = (
        _ArtifactStep("alpha"),
        _ArtifactStep("beta"),
        _ArtifactStep("gamma"),
    )
    pipeline = Pipeline(blueprint, workspace=workspace)
    pipeline.run(_initial_state(workspace, "run-C"))

    (workspace / "artefacts" / "beta.txt").unlink()

    catalog = SimulationCatalog(workspace)
    try:
        journal = WorkflowJournal(catalog)
        planner = ResumePlanner(journal, workspace)
        plan = planner.compute(
            run_id="run-C",
            current_config_sha256=None,
            steps_blueprint=tuple(s.name for s in blueprint),
        )
        assert plan.restart_index == 1
        assert plan.last_completed is not None
        assert plan.last_completed.step_name == "alpha"
    finally:
        catalog.close()

    # Allow short jitter between heartbeats and the next start
    time.sleep(0.01)

    recovery = (
        _ArtifactStep("alpha"),
        _ArtifactStep("beta"),
        _ArtifactStep("gamma"),
    )
    pipeline = Pipeline(recovery, workspace=workspace)
    final = pipeline.run(_initial_state(workspace, "run-C"), resume_from=1)
    assert final.get("completed") == ["beta", "gamma"]

    catalog = SimulationCatalog(workspace)
    try:
        journal = WorkflowJournal(catalog)
        rows = journal.list_steps("run-C")
        assert [r.status for r in rows] == ["completed", "completed", "completed"]
    finally:
        catalog.close()
