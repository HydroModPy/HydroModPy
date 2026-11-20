"""Where a run restarts, from the step journal and the artifacts of its steps.

A step is trusted when its row is completed, its artifacts exist and their hash still
matches. The first step that fails this and all after it are aborted and run again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.workflow.record.journal import WorkflowJournal
from hydromodpy.workflow.record.resume import ResumePlan, ResumePlanner

BLUEPRINT = ("resolve", "load", "mesh", "solve", "extract")
SHARED_STORE = ("store/fields.zarr",)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def journal(workspace: Path) -> WorkflowJournal:
    return WorkflowJournal(workspace / "runs" / "case")


def complete_step(
    journal: WorkflowJournal,
    workspace: Path,
    run_id: str,
    order: int,
    name: str,
    artifacts: tuple[str, ...] | None = None,
) -> None:
    """Journal a completed step and write the files it declares (default `<name>/output.txt`)."""
    artifacts = (f"{name}/output.txt",) if artifacts is None else artifacts
    step_id = journal.start_step(
        run_id=run_id, step_order=order, step_name=name, inputs_hash=f"in-{order}"
    )
    for uri in artifacts:
        target = workspace / uri
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"content for {name}", encoding="utf-8")
    journal.finish_step(
        step_id=step_id,
        status="completed",
        outputs_hash=WorkflowJournal.compute_outputs_hash(workspace, artifacts),
        artifact_uris=artifacts,
    )


def plan_of(journal: WorkflowJournal, workspace: Path, run_id: str, blueprint=BLUEPRINT):
    return ResumePlanner(journal, workspace).compute(
        run_id=run_id, current_config_sha256="cfg", steps_blueprint=blueprint
    )


def test_no_journal_entries_is_a_fresh_start(journal, workspace) -> None:
    plan = plan_of(journal, workspace, "never-ran")
    assert isinstance(plan, ResumePlan)
    assert plan.restart_index == 0
    assert plan.last_completed is None
    assert plan.invalidated == ()
    assert plan.full_restart is False
    assert plan.reason == "no journal entries"


def test_resume_after_a_failed_step(journal, workspace) -> None:
    for order, name in enumerate(BLUEPRINT[:3]):
        complete_step(journal, workspace, "r1", order, name)
    failed_id = journal.start_step(run_id="r1", step_order=3, step_name="solve", inputs_hash="in-3")
    journal.finish_step(step_id=failed_id, status="failed", error_message="boom")

    plan = plan_of(journal, workspace, "r1")

    assert plan.restart_index == 3
    assert plan.last_completed.step_name == "mesh"
    assert plan.invalidated == ()
    assert plan.full_restart is False


def test_missing_artifact_invalidates_from_its_step(journal, workspace) -> None:
    for order, name in enumerate(BLUEPRINT[:3]):
        complete_step(journal, workspace, "r2", order, name)
    (workspace / "load" / "output.txt").unlink()

    plan = plan_of(journal, workspace, "r2")

    assert plan.restart_index == 1
    assert plan.last_completed.step_name == "resolve"
    assert [row.step_name for row in plan.invalidated] == ["load"]
    assert "artifact missing" in plan.invalidated[0].reason
    # The invalidated step and the one after it are aborted.
    assert [r.status for r in journal.list_steps("r2")] == ["completed", "aborted", "aborted"]


def test_changed_artifact_invalidates_from_its_step(journal, workspace) -> None:
    for order, name in enumerate(BLUEPRINT[:2]):
        complete_step(journal, workspace, "r3", order, name)
    (workspace / "load" / "output.txt").write_text("tampered", encoding="utf-8")

    plan = plan_of(journal, workspace, "r3")

    assert plan.restart_index == 1
    assert plan.last_completed.step_name == "resolve"
    assert plan.invalidated and "outputs_hash mismatch" in plan.invalidated[0].reason


def test_changed_blueprint_restarts_in_full(journal, workspace) -> None:
    for order, name in enumerate(BLUEPRINT[:2]):
        complete_step(journal, workspace, "r4", order, name)

    plan = plan_of(
        journal, workspace, "r4", blueprint=("resolve", "transform", "mesh", "solve", "extract")
    )

    assert plan.full_restart is True
    assert plan.restart_index == 0
    assert plan.last_completed is None
    assert "blueprint" in (plan.reason or "")
    assert all(r.status == "aborted" for r in journal.list_steps("r4"))


def test_shared_store_is_checked_by_existence_only(journal, workspace) -> None:
    # Two steps write into one run store, so the first digest goes stale once the second writes.
    complete_step(journal, workspace, "r7", 0, "resolve", SHARED_STORE)
    complete_step(journal, workspace, "r7", 1, "load", SHARED_STORE)
    rows = journal.list_steps("r7")
    assert rows[0].outputs_hash != rows[1].outputs_hash

    plan = plan_of(journal, workspace, "r7")

    assert plan.invalidated == ()
    assert plan.restart_index == 2


def test_shared_store_must_exist(journal, workspace) -> None:
    complete_step(journal, workspace, "r8", 0, "resolve", SHARED_STORE)
    complete_step(journal, workspace, "r8", 1, "load", SHARED_STORE)
    (workspace / "store" / "fields.zarr").unlink()

    plan = plan_of(journal, workspace, "r8")

    assert plan.restart_index == 0
    assert plan.invalidated and "artifact missing" in plan.invalidated[0].reason
