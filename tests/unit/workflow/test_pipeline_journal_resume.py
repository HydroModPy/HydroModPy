"""Pipeline resume driven by the workflow_steps journal.

Replaces the legacy pickle-based checkpoint tests. Each scenario exercises
a small synthetic pipeline against a real :class:`Catalog`, then
asserts the journal rows and the absence of pickle artefacts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import StepError
from hydromodpy.results.catalog import Catalog
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.journal import WorkflowJournal
from hydromodpy.workflow.runner import Pipeline


class _AddOne:
    name = "add_one"

    def run(self, state: PipelineState) -> PipelineState:
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            counter=state.data.get("counter", 0) + 1,
        )


class _Double:
    name = "double"

    def run(self, state: PipelineState) -> PipelineState:
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            counter=state.data.get("counter", 0) * 2,
        )


class _Crash:
    name = "crash"

    def run(self, state: PipelineState) -> PipelineState:
        raise RuntimeError("simulated crash")


class _RecoveredCrash:
    name = "crash"

    def run(self, state: PipelineState) -> PipelineState:
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            counter=state.data.get("counter", 0) + 1,
        )


def _journal_for(workspace: Path) -> tuple[WorkflowJournal, Catalog]:
    catalog = Catalog(workspace)
    return WorkflowJournal(catalog), catalog


def test_full_run_records_completed_rows(tmp_path: Path) -> None:
    pipeline = Pipeline([_AddOne(), _AddOne(), _Double()], workspace=tmp_path)
    state = PipelineState(run_id="r1", data={"counter": 0})
    final = pipeline.run(state)
    assert final.data["counter"] == 4

    journal, catalog = _journal_for(tmp_path)
    try:
        rows = journal.list_steps("r1")
        assert [r.step_name for r in rows] == ["add_one", "add_one", "double"]
        assert all(r.status == "completed" for r in rows)
    finally:
        catalog.close()


def test_crash_then_resume_replays_only_remaining(tmp_path: Path) -> None:
    state = PipelineState(run_id="crash-1", data={"counter": 5})
    crashing = Pipeline([_AddOne(), _Crash(), _Double()], workspace=tmp_path)
    with pytest.raises(StepError) as info:
        crashing.run(state)
    assert info.value.step_name == "crash"

    journal, catalog = _journal_for(tmp_path)
    try:
        rows = journal.list_steps("crash-1")
        statuses = [(r.step_order, r.status) for r in rows]
        assert statuses == [(0, "completed"), (1, "failed")]
    finally:
        catalog.close()

    # State-from-artifacts: in-memory step 0 is re-executed from the supplied
    # initial state. We pass the same input (counter=5) so step 0 re-runs to 6,
    # then the recovered step bumps to 7, and double yields 14.
    fixed = Pipeline([_AddOne(), _RecoveredCrash(), _Double()], workspace=tmp_path)
    final = fixed.run(PipelineState(run_id="crash-1", data={"counter": 5}), resume_from=1)
    assert final.step_name == "double"
    assert final.data["counter"] == 14

    journal, catalog = _journal_for(tmp_path)
    try:
        rows = journal.list_steps("crash-1")
        assert [r.status for r in rows] == ["completed", "completed", "completed"]
    finally:
        catalog.close()


def test_resume_without_journal_starts_from_scratch(tmp_path: Path) -> None:
    pipeline = Pipeline([_AddOne()], workspace=tmp_path)
    state = PipelineState(run_id="fresh", data={"counter": 99})
    final = pipeline.run(state, resume_from=0)
    assert final.data["counter"] == 100


def test_no_pickle_files_produced(tmp_path: Path) -> None:
    pipeline = Pipeline([_AddOne(), _AddOne()], workspace=tmp_path)
    pipeline.run(PipelineState(run_id="no-pkl", data={"counter": 0}))
    pickle_dir = tmp_path / ".hmp" / "checkpoints" / "no-pkl"
    if pickle_dir.exists():
        for entry in pickle_dir.iterdir():
            assert entry.suffix not in (".pkl", ".pkl.zst")
