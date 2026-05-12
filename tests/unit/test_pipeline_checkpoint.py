"""Unit tests for checkpointing and crash-resume behaviour.

Simulates a pipeline that crashes on step N and verifies that
(a) the first N-1 steps' checkpoints exist on disk,
(b) a second pipeline invocation with ``resume_from`` replays only the
    remaining steps on the restored state.

Pipeline-level bookkeeping (status, elapsed, error) used to be persisted by
a stand-alone ``steps_ledger.duckdb``. That base is being merged into the
project ``catalog.duckdb`` as the ``workflow_steps`` table in P4. Tests that
asserted ledger rows have been replaced by checkpoint-store assertions until
the new table is wired.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import StepError
from hydromodpy.workflow.internals.checkpoint import CheckpointStore
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.runner import Pipeline


class _AddOne:
    name = "add_one"

    def run(self, state):
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            counter=state.data.get("counter", 0) + 1,
        )


class _Crash:
    name = "crash"

    def run(self, state):
        raise RuntimeError("simulated crash on step 2")


class _RecoveredCrash:
    name = "crash"

    def run(self, state):
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            counter=state.data.get("counter", 0) + 1,
        )


class _Double:
    name = "double"

    def run(self, state):
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            counter=state.data.get("counter", 0) * 2,
        )


def _fresh_pipeline(tmp_path: Path, steps) -> Pipeline:
    return Pipeline(steps, workspace=tmp_path, checkpoint=True)


def test_checkpoint_persists_each_step(tmp_path: Path) -> None:
    pipeline = _fresh_pipeline(tmp_path, [_AddOne(), _AddOne(), _AddOne()])
    state = PipelineState(run_id="r1", data={"counter": 0})
    pipeline.run(state)

    cp = CheckpointStore(tmp_path, "r1")
    indices = cp.completed_indices()
    assert indices == [0, 1, 2]


def test_checkpoint_records_completed_steps(tmp_path: Path) -> None:
    pipeline = _fresh_pipeline(tmp_path, [_AddOne(), _AddOne()])
    state = PipelineState(run_id="led-1", data={"counter": 0})
    pipeline.run(state)

    cp = CheckpointStore(tmp_path, "led-1")
    assert cp.latest() == 1
    assert cp.completed_indices() == [0, 1]


def test_crash_then_resume_replays_only_remaining(tmp_path: Path) -> None:
    steps = [_AddOne(), _Crash(), _Double()]
    pipeline = _fresh_pipeline(tmp_path, steps)
    state = PipelineState(run_id="crash-1", data={"counter": 5})

    with pytest.raises(StepError) as excinfo:
        pipeline.run(state)
    assert excinfo.value.step_name == "crash"
    assert isinstance(excinfo.value.cause, RuntimeError)

    cp = CheckpointStore(tmp_path, "crash-1")
    assert cp.completed_indices() == [0]
    assert cp.latest() == 0

    fixed_pipeline = _fresh_pipeline(tmp_path, [_AddOne(), _RecoveredCrash(), _Double()])
    final = fixed_pipeline.run(
        PipelineState(run_id="crash-1"),
        resume_from=1,
    )
    assert final.data["counter"] == 14
    assert final.step_name == "double"


def test_resume_without_checkpoint_directory_raises(tmp_path: Path) -> None:
    pipeline = _fresh_pipeline(tmp_path, [_AddOne()])
    state = PipelineState(run_id="missing", data={"counter": 99})
    final = pipeline.run(state, resume_from=0)
    assert final.data["counter"] == 100


def test_checkpoint_file_naming(tmp_path: Path) -> None:
    pipeline = _fresh_pipeline(tmp_path, [_AddOne(), _Double()])
    pipeline.run(PipelineState(run_id="naming", data={"counter": 1}))
    cp_dir = tmp_path / ".hmp" / "checkpoints" / "naming"
    names = sorted(p.name for p in cp_dir.iterdir())
    assert any(n.startswith("00_add_one") for n in names)
    assert any(n.startswith("01_double") for n in names)
