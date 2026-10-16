"""Pipeline resume driven by the step journal of the run directory.

Each scenario exercises a small synthetic pipeline whose run directory is the
temporary folder, then asserts the journal rows and the absence of pickle
artefacts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import StepError
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.runner import Pipeline
from hydromodpy.workflow.tracking.journal import WorkflowJournal


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


def _pipeline(steps, root: Path) -> Pipeline:
    return Pipeline(steps, workspace=root, run_dir=root)


def _rows(root: Path, run_id: str):
    return WorkflowJournal(root).list_steps(run_id)


def test_full_run_records_completed_rows(tmp_path: Path) -> None:
    pipeline = _pipeline([_AddOne(), _AddOne(), _Double()], tmp_path)
    state = PipelineState(run_id="r1", data={"counter": 0})
    final = pipeline.run(state)
    assert final.data["counter"] == 4

    rows = _rows(tmp_path, "r1")
    assert [r.step_name for r in rows] == ["add_one", "add_one", "double"]
    assert all(r.status == "completed" for r in rows)


def test_crash_then_resume_replays_only_remaining(tmp_path: Path) -> None:
    state = PipelineState(run_id="crash-1", data={"counter": 5})
    crashing = _pipeline([_AddOne(), _Crash(), _Double()], tmp_path)
    with pytest.raises(StepError) as info:
        crashing.run(state)
    assert info.value.step_name == "crash"

    rows = _rows(tmp_path, "crash-1")
    statuses = [(r.step_order, r.status) for r in rows]
    assert statuses == [(0, "completed"), (1, "failed")]

    # State-from-artifacts: in-memory step 0 is re-executed from the supplied
    # initial state. We pass the same input (counter=5) so step 0 re-runs to 6,
    # then the recovered step bumps to 7, and double yields 14.
    fixed = _pipeline([_AddOne(), _RecoveredCrash(), _Double()], tmp_path)
    final = fixed.run(PipelineState(run_id="crash-1", data={"counter": 5}), resume_from=1)
    assert final.step_name == "double"
    assert final.data["counter"] == 14

    rows = _rows(tmp_path, "crash-1")
    assert [r.status for r in rows] == ["completed", "completed", "completed"]


def test_resume_without_journal_starts_from_scratch(tmp_path: Path) -> None:
    pipeline = _pipeline([_AddOne()], tmp_path)
    state = PipelineState(run_id="fresh", data={"counter": 99})
    final = pipeline.run(state, resume_from=0)
    assert final.data["counter"] == 100


def test_no_pickle_files_produced(tmp_path: Path) -> None:
    pipeline = _pipeline([_AddOne(), _AddOne()], tmp_path)
    pipeline.run(PipelineState(run_id="no-pkl", data={"counter": 0}))
    pickle_dir = tmp_path / ".hmp" / "checkpoints"
    if pickle_dir.exists():
        for entry in pickle_dir.iterdir():
            assert entry.suffix not in (".pkl", ".pkl.zst")


def test_model_phase_ready_rerun_survives_config_change(tmp_path: Path) -> None:
    """A plain re-run with an edited config must not abort as a stale resume.

    Regression: the model-phase-ready optimisation sets ``resume_from > 0`` (it
    only skips the in-process model phase). That used to trip
    ``manifest.verify_state`` against the prior same-name run's checkpoint and
    raise ``ResumeError`` whenever the config changed (e.g. edit Sy, re-run
    ``hmp run``). ``model_phase_ready=True`` marks it as a fresh run instead.
    """
    from hydromodpy.core.exceptions import ResumeError

    steps = [_AddOne(), _AddOne(), _Double()]
    _pipeline(steps, tmp_path).run(
        PipelineState(run_id="r", data={"counter": 0, "raw_toml": {"flow": {"sy": 0.001}}})
    )

    changed = PipelineState(run_id="r", data={"counter": 0, "raw_toml": {"flow": {"sy": 0.0001}}})
    final = _pipeline(steps, tmp_path).run(changed, resume_from=2, model_phase_ready=True)
    assert final.data["counter"] == 4

    # A genuine resume still verifies the checkpoint and rejects the change.
    stale = PipelineState(run_id="r", data={"counter": 0, "raw_toml": {"flow": {"sy": 0.5}}})
    with pytest.raises(ResumeError):
        _pipeline(steps, tmp_path).run(stale, resume_from=2, model_phase_ready=False)
