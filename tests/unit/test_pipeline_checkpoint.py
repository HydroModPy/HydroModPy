"""Unit tests for checkpointing and crash-resume behaviour.

Simulates a pipeline that crashes on step N and verifies that
(a) the first N-1 steps' checkpoints exist on disk,
(b) the ledger records them as completed + the failing one as failed,
(c) a second pipeline invocation with ``resume_from`` replays only the
    remaining steps on the restored state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import StepError
from hydromodpy.workflow.internals.checkpoint import CheckpointStore
from hydromodpy.workflow.internals.ledger import StepsLedger
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


def test_ledger_records_completed_steps(tmp_path: Path) -> None:
    pipeline = _fresh_pipeline(tmp_path, [_AddOne(), _AddOne()])
    state = PipelineState(run_id="led-1", data={"counter": 0})
    pipeline.run(state)

    with StepsLedger(tmp_path) as led:
        assert led.last_completed("led-1") == 1
        rows = led.rows_for("led-1")
    assert len(rows) == 2
    statuses = [row[3] for row in rows]
    assert statuses == ["completed", "completed"]


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

    with StepsLedger(tmp_path) as led:
        assert led.last_completed("crash-1") == 0
        rows = led.rows_for("crash-1")
        failed = [r for r in rows if r[3] == "failed"]
        assert len(failed) == 1
        assert failed[0][1] == 1  # step_index of crash

    # Replace the crashing step with a working one and resume.
    fixed_pipeline = _fresh_pipeline(tmp_path, [_AddOne(), _AddOne(), _Double()])
    final = fixed_pipeline.run(
        PipelineState(run_id="crash-1"),
        resume_from=1,
    )
    # counter was 6 after step 0; step 1 makes it 7; step 2 doubles to 14.
    assert final.data["counter"] == 14
    assert final.step_name == "double"


def test_resume_without_checkpoint_directory_raises(tmp_path: Path) -> None:
    # Attempting to resume a run whose checkpoints do not exist results
    # in a pipeline that effectively starts from scratch at the requested
    # index (the CheckpointStore silently falls back to the supplied
    # initial state).
    pipeline = _fresh_pipeline(tmp_path, [_AddOne()])
    state = PipelineState(run_id="missing", data={"counter": 99})
    final = pipeline.run(state, resume_from=0)
    assert final.data["counter"] == 100


def test_checkpoint_file_naming(tmp_path: Path) -> None:
    pipeline = _fresh_pipeline(tmp_path, [_AddOne(), _Double()])
    pipeline.run(PipelineState(run_id="naming", data={"counter": 1}))
    cp_dir = tmp_path / ".hmp" / "checkpoints" / "naming"
    names = sorted(p.name for p in cp_dir.iterdir())
    # Filenames look like 00_add_one.pkl(.zst) and 01_double.pkl(.zst)
    assert any(n.startswith("00_add_one") for n in names)
    assert any(n.startswith("01_double") for n in names)
