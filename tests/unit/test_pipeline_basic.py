"""Unit tests for the :class:`hydromodpy.pipeline.Pipeline` orchestrator.

Covers the linear execution contract: state flows between steps, step
metadata (index, name, elapsed) is populated, and the final state is
produced by the last step.
"""

from __future__ import annotations

import pytest

from hydromodpy.pipeline import Pipeline, PipelineState, Step


class _AddOne:
    """Minimal step that increments ``data['counter']`` by 1."""

    name = "add_one"

    def run(self, state: PipelineState) -> PipelineState:
        counter = state.data.get("counter", 0) + 1
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            counter=counter,
        )


class _Multiply:
    name = "multiply"

    def __init__(self, factor: int) -> None:
        self.factor = factor

    def run(self, state: PipelineState) -> PipelineState:
        counter = state.data.get("counter", 0) * self.factor
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            counter=counter,
        )


class _Fail:
    name = "fail"

    def run(self, state: PipelineState) -> PipelineState:
        raise RuntimeError("boom")


def test_step_protocol_is_satisfied() -> None:
    assert isinstance(_AddOne(), Step)
    assert isinstance(_Multiply(3), Step)


def test_linear_pipeline_runs_all_steps() -> None:
    state = PipelineState(run_id="r", data={"counter": 0})
    pipeline = Pipeline([_AddOne(), _AddOne(), _Multiply(5)])
    final = pipeline.run(state)
    assert final.data["counter"] == 10  # (0+1+1)*5
    assert final.step_name == "multiply"
    assert final.step_index == 2


def test_pipeline_preserves_run_id() -> None:
    state = PipelineState(run_id="my-run-42", data={"counter": 7})
    pipeline = Pipeline([_AddOne()])
    final = pipeline.run(state)
    assert final.run_id == "my-run-42"


def test_pipeline_records_elapsed_ms_for_each_step() -> None:
    state = PipelineState(run_id="r", data={"counter": 0})
    pipeline = Pipeline([_AddOne(), _AddOne()])
    final = pipeline.run(state)
    assert final.elapsed_ms >= 0.0


def test_pipeline_run_without_workspace_skips_ledger() -> None:
    # No workspace → no ledger / no checkpoint store. Must still run.
    state = PipelineState(run_id="r", data={"counter": 0})
    pipeline = Pipeline([_AddOne()])
    final = pipeline.run(state)
    assert final.data["counter"] == 1


def test_pipeline_propagates_exception() -> None:
    state = PipelineState(run_id="r")
    pipeline = Pipeline([_AddOne(), _Fail()])
    with pytest.raises(RuntimeError, match="boom"):
        pipeline.run(state)


def test_pipeline_resume_from_skips_early_steps() -> None:
    state = PipelineState(run_id="r", data={"counter": 100})
    pipeline = Pipeline([_AddOne(), _AddOne(), _Multiply(10)])
    # resume_from=2 → only Multiply runs on the supplied state as-is.
    final = pipeline.run(state, resume_from=2)
    assert final.data["counter"] == 1000
    assert final.step_name == "multiply"


def test_state_advance_preserves_run_id_and_updates_step_metadata() -> None:
    state = PipelineState(run_id="abc", data={"x": 1})
    nxt = state.advance(step_index=5, step_name="foo", x=2)
    assert nxt.run_id == "abc"
    assert nxt.step_index == 5
    assert nxt.step_name == "foo"
    assert nxt.data == {"x": 2}


def test_state_is_immutable() -> None:
    state = PipelineState(run_id="r", data={"x": 1})
    with pytest.raises(Exception):
        state.step_index = 99  # type: ignore[misc]
