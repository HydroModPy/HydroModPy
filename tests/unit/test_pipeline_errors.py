"""Unit tests for the :class:`PipelineError` hierarchy and its wrapping."""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import (
    CheckpointError,
    HydroModPyError,
    LedgerError,
    PipelineError,
    ResumeError,
    StepError,
)
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.runner import Pipeline


class _RaisesValueError:
    name = "boom"

    def run(self, state):
        raise ValueError("upstream cause")


class _RaisesKeyboardInterrupt:
    name = "interrupt"

    def run(self, state):
        raise KeyboardInterrupt()


# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------


def test_pipeline_error_inherits_hydromodpy_base() -> None:
    assert issubclass(PipelineError, HydroModPyError)


@pytest.mark.parametrize(
    "subclass",
    [StepError, CheckpointError, LedgerError, ResumeError],
)
def test_pipeline_subclasses_inherit_pipeline_error(subclass) -> None:
    assert issubclass(subclass, PipelineError)


def test_each_pipeline_error_class_has_distinct_code() -> None:
    codes = {
        PipelineError.code,
        StepError.code,
        CheckpointError.code,
        LedgerError.code,
        ResumeError.code,
    }
    assert len(codes) == 5


def test_pipeline_error_codes_match_e500_range() -> None:
    assert PipelineError.code == "HMPY.E500"
    assert StepError.code == "HMPY.E501"
    assert CheckpointError.code == "HMPY.E502"
    assert LedgerError.code == "HMPY.E503"
    assert ResumeError.code == "HMPY.E504"


# ---------------------------------------------------------------------------
# StepError canonical constructor
# ---------------------------------------------------------------------------


def test_step_error_carries_step_name_and_cause() -> None:
    cause = ValueError("bad")
    err = StepError("validate", cause, run_id="r-42")
    assert err.step_name == "validate"
    assert err.cause is cause
    assert err.run_id == "r-42"
    assert "validate" in str(err)
    assert "bad" in str(err)


def test_step_error_propagates_extra_context() -> None:
    err = StepError("x", RuntimeError("boom"), sim_id="s1", run_id="r1", extra="meta")
    assert err.sim_id == "s1"
    assert err.run_id == "r1"
    assert err.context == {"extra": "meta"}


# ---------------------------------------------------------------------------
# Pipeline wraps step exceptions in StepError
# ---------------------------------------------------------------------------


def test_pipeline_wraps_arbitrary_exception_in_step_error() -> None:
    pipeline = Pipeline([_RaisesValueError()])
    state = PipelineState(run_id="r-1", data={})
    with pytest.raises(StepError) as excinfo:
        pipeline.run(state)
    err = excinfo.value
    assert err.step_name == "boom"
    assert err.run_id == "r-1"
    assert isinstance(err.cause, ValueError)
    assert isinstance(err.__cause__, ValueError)


def test_pipeline_does_not_wrap_keyboard_interrupt() -> None:
    pipeline = Pipeline([_RaisesKeyboardInterrupt()])
    state = PipelineState(run_id="r", data={})
    with pytest.raises(KeyboardInterrupt):
        pipeline.run(state)


def test_pipeline_does_not_double_wrap_step_error() -> None:
    class _RaisesStepError:
        name = "already_typed"

        def run(self, state):
            raise StepError("already_typed", RuntimeError("inner"), run_id="r")

    pipeline = Pipeline([_RaisesStepError()])
    with pytest.raises(StepError) as excinfo:
        pipeline.run(PipelineState(run_id="r", data={}))
    # Re-raised as-is (not wrapped a second time): cause stays the original.
    assert isinstance(excinfo.value.cause, RuntimeError)
    assert excinfo.value.step_name == "already_typed"
