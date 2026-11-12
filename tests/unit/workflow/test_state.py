"""PipelineState and the payload keys each step exposes."""

from __future__ import annotations

import pytest

from hydromodpy.workflow.state import PipelineState

# --- test_pipeline_state ---
# The pipeline payload is a mapping, and each step says which keys it touches.
#
# Eleven frozen payload classes used to be declared beside ``PipelineState``,
# ``ValidatedState`` through ``ExportedState``, and this file tested their
# inheritance chain, their frozenness and the ``tin`` / ``tout`` pair that named
# them. None of it described the running pipeline: the classes had zero
# instantiations, and the runner cannot consume a non-mapping payload anyway - it
# unions ``dict(base_state.data)`` to merge a parallel cohort. What is tested here
# is what the payload is.

STEP_ORDER = (
    "ValidateStep",
    "ResolveStep",
    "BuildGeographicStep",
    "LoadDataStep",
    "BuildMeshStep",
    "SetupProcessStep",
    "PrepareSolverStep",
    "RunSolverStep",
    "ExtractStep",
    "DeriveStep",
    "ExportStep",
)


# ``DisplayStep`` is a step of the package but not of the standard pipeline; the
# declaration checks cover it, the phase-order check cannot.
ALL_STEPS = (*STEP_ORDER, "DisplayStep")


# ---------------------------------------------------------------------------
# The payload
# ---------------------------------------------------------------------------


def test_a_state_defaults_to_an_empty_payload() -> None:
    assert PipelineState(run_id="r").data == {}


def test_a_state_is_frozen() -> None:
    state = PipelineState(run_id="r")
    with pytest.raises(AttributeError):
        state.run_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# What a step declares about the payload
# ---------------------------------------------------------------------------


def _step_classes() -> dict[str, type]:
    from hydromodpy.workflow.steps.sequence import standard_steps

    built = {type(step).__name__: type(step) for step in standard_steps()}
    return {name: built[name] for name in ALL_STEPS}
