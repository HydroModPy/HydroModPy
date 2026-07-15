"""Unit tests for ResumePlanner."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.workflow.tracking.journal import WorkflowJournal
from hydromodpy.workflow.tracking.resume import ResumePlan, ResumePlanner
from tests._helpers.fixtures_catalog import simulation_catalog

BLUEPRINT = ("resolve", "load", "mesh", "solve", "extract")


@pytest.fixture
def catalog(tmp_path: Path) -> Catalog:
    with simulation_catalog(tmp_path) as cat:
        yield cat


@pytest.fixture
def workspace(catalog: Catalog) -> Path:
    return catalog.workspace_path


@pytest.fixture
def journal(catalog: Catalog) -> WorkflowJournal:
    return WorkflowJournal(catalog)


def _seed_completed_step(
    journal: WorkflowJournal,
    workspace: Path,
    *,
    run_id: str,
    step_order: int,
    step_name: str,
    artifact_uris: tuple[str, ...] = (),
    create_artifacts: bool = True,
) -> str:
    step_id = journal.start_step(
        run_id=run_id,
        step_order=step_order,
        step_name=step_name,
        inputs_hash=f"in-{step_order}",
    )
    materialised: tuple[str, ...] = ()
    if create_artifacts:
        for uri in artifact_uris:
            target = workspace / uri
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"content for {step_name}", encoding="utf-8")
        materialised = artifact_uris
    outputs_hash = (
        WorkflowJournal.compute_outputs_hash(workspace, materialised) if materialised else None
    )
    journal.finish_step(
        step_id=step_id,
        status="completed",
        outputs_hash=outputs_hash,
        artifact_uris=materialised,
    )
    return step_id


def test_no_journal_entries_means_fresh_start(journal: WorkflowJournal, workspace: Path) -> None:
    planner = ResumePlanner(journal, workspace)
    plan = planner.compute(
        run_id="never-ran",
        current_config_sha256="cfg",
        steps_blueprint=BLUEPRINT,
    )
    assert isinstance(plan, ResumePlan)
    assert plan.restart_index == 0
    assert plan.last_completed is None
    assert plan.invalidated == ()
    assert plan.full_restart is False
    assert plan.reason == "no journal entries"


def test_resume_after_three_completed_and_one_failed(
    journal: WorkflowJournal, workspace: Path
) -> None:
    for order, name in enumerate(BLUEPRINT[:3]):
        _seed_completed_step(
            journal,
            workspace,
            run_id="r1",
            step_order=order,
            step_name=name,
            artifact_uris=(f"out/{name}.txt",),
        )
    failed_id = journal.start_step(
        run_id="r1",
        step_order=3,
        step_name="solve",
        inputs_hash="in-3",
    )
    journal.finish_step(step_id=failed_id, status="failed", error_message="boom")

    planner = ResumePlanner(journal, workspace)
    plan = planner.compute(
        run_id="r1",
        current_config_sha256="cfg",
        steps_blueprint=BLUEPRINT,
    )
    assert plan.restart_index == 3
    assert plan.last_completed is not None
    assert plan.last_completed.step_name == "mesh"
    assert plan.invalidated == ()
    assert plan.full_restart is False


def test_missing_artifact_invalidates_from_step(journal: WorkflowJournal, workspace: Path) -> None:
    _seed_completed_step(
        journal,
        workspace,
        run_id="r2",
        step_order=0,
        step_name="resolve",
        artifact_uris=("resolve/output.txt",),
    )
    _seed_completed_step(
        journal,
        workspace,
        run_id="r2",
        step_order=1,
        step_name="load",
        artifact_uris=("load/output.txt",),
    )
    _seed_completed_step(
        journal,
        workspace,
        run_id="r2",
        step_order=2,
        step_name="mesh",
        artifact_uris=("mesh/output.txt",),
    )
    (workspace / "load" / "output.txt").unlink()

    planner = ResumePlanner(journal, workspace)
    plan = planner.compute(
        run_id="r2",
        current_config_sha256="cfg",
        steps_blueprint=BLUEPRINT,
    )
    assert plan.restart_index == 1
    assert plan.last_completed is not None
    assert plan.last_completed.step_name == "resolve"
    assert len(plan.invalidated) == 1
    assert plan.invalidated[0].step_name == "load"
    assert "artifact missing" in plan.invalidated[0].reason

    rows_after = journal.list_steps("r2")
    statuses = [r.status for r in rows_after]
    assert statuses == ["completed", "aborted", "aborted"]


def test_hash_mismatch_invalidates_and_restarts(journal: WorkflowJournal, workspace: Path) -> None:
    _seed_completed_step(
        journal,
        workspace,
        run_id="r3",
        step_order=0,
        step_name="resolve",
        artifact_uris=("resolve/output.txt",),
    )
    _seed_completed_step(
        journal,
        workspace,
        run_id="r3",
        step_order=1,
        step_name="load",
        artifact_uris=("load/output.txt",),
    )
    (workspace / "load" / "output.txt").write_text("tampered", encoding="utf-8")

    planner = ResumePlanner(journal, workspace)
    plan = planner.compute(
        run_id="r3",
        current_config_sha256="cfg",
        steps_blueprint=BLUEPRINT,
    )
    assert plan.restart_index == 1
    assert plan.last_completed is not None
    assert plan.last_completed.step_name == "resolve"
    assert plan.invalidated and "outputs_hash mismatch" in plan.invalidated[0].reason


def test_blueprint_mismatch_forces_full_restart(journal: WorkflowJournal, workspace: Path) -> None:
    _seed_completed_step(
        journal,
        workspace,
        run_id="r4",
        step_order=0,
        step_name="resolve",
        artifact_uris=("resolve/output.txt",),
    )
    _seed_completed_step(
        journal,
        workspace,
        run_id="r4",
        step_order=1,
        step_name="load",
        artifact_uris=("load/output.txt",),
    )
    altered = ("resolve", "transform", "mesh", "solve", "extract")

    planner = ResumePlanner(journal, workspace)
    plan = planner.compute(
        run_id="r4",
        current_config_sha256="cfg",
        steps_blueprint=altered,
    )
    assert plan.full_restart is True
    assert plan.restart_index == 0
    assert plan.last_completed is None
    assert "blueprint" in (plan.reason or "")
    rows = journal.list_steps("r4")
    assert all(r.status == "aborted" for r in rows)


def test_restart_index_after_all_completed(journal: WorkflowJournal, workspace: Path) -> None:
    for order, name in enumerate(BLUEPRINT):
        _seed_completed_step(
            journal,
            workspace,
            run_id="r5",
            step_order=order,
            step_name=name,
            artifact_uris=(f"{name}/output.txt",),
        )
    planner = ResumePlanner(journal, workspace)
    plan = planner.compute(
        run_id="r5",
        current_config_sha256="cfg",
        steps_blueprint=BLUEPRINT,
    )
    assert plan.restart_index == len(BLUEPRINT)
    assert plan.last_completed is not None
    assert plan.last_completed.step_name == BLUEPRINT[-1]
    assert plan.invalidated == ()
