"""The pipeline payload is a mapping, and each step says which keys it touches.

Eleven frozen payload classes used to be declared beside ``PipelineState``,
``ValidatedState`` through ``ExportedState``, and this file tested their
inheritance chain, their frozenness and the ``tin`` / ``tout`` pair that named
them. None of it described the running pipeline: the classes had zero
instantiations, and the runner cannot consume a non-mapping payload anyway - it
unions ``dict(base_state.data)`` to merge a parallel cohort. What is tested here
is what the payload is.
"""

from __future__ import annotations

import pytest

from hydromodpy.workflow.internals.state import PipelineState

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


def test_advance_merges_keyword_arguments_into_the_payload() -> None:
    state = PipelineState(run_id="r", data={"counter": 0, "kept": "yes"})
    nxt = state.advance(step_index=1, step_name="x", counter=5)
    assert nxt.data == {"counter": 5, "kept": "yes"}
    assert nxt.step_name == "x"
    assert nxt.run_id == "r"


def test_advance_merges_keyword_arguments_into_an_explicit_payload() -> None:
    """The runner's resume path passes ``data=`` and the step adds keys on top."""
    state = PipelineState(run_id="r", data={"stale": 1})
    nxt = state.advance(step_index=1, step_name="x", data={"fresh": 1}, added=2)
    assert nxt.data == {"fresh": 1, "added": 2}


def test_advance_does_not_alias_the_payload_it_came_from() -> None:
    """A successor owns its payload: a later write must not reach backwards."""
    state = PipelineState(run_id="r", data={"counter": 0})
    nxt = state.advance(step_index=1, step_name="x")
    assert nxt.data == state.data
    assert nxt.data is not state.data


def test_advance_does_not_alias_an_explicit_payload_either() -> None:
    """The runner's own shape: ``data=`` alone, no keyword to merge on top.

    ``Pipeline._execute_step`` and the skipped-step path both call
    ``advance(data=<a payload that already exists>)``. Handing the successor the
    very same dict would make two states share one mapping, and a write through
    either would be visible from the other. It is copied.
    """
    payload = {"counter": 0}
    state = PipelineState(run_id="r", data={"stale": 1})
    nxt = state.advance(step_index=1, step_name="x", data=payload)
    assert nxt.data == payload
    assert nxt.data is not payload


def test_a_state_is_frozen() -> None:
    state = PipelineState(run_id="r")
    with pytest.raises(AttributeError):
        state.run_id = "other"  # type: ignore[misc]


def test_get_reads_the_payload_with_a_default() -> None:
    state = PipelineState(run_id="r", data={"ctx": "the-context"})
    assert state.get("ctx") == "the-context"
    assert state.get("missing", "default") == "default"
    assert state.get("missing") is None


def test_with_data_merges_without_moving_the_step_position() -> None:
    state = PipelineState(run_id="r", step_index=3, step_name="build_mesh", data={"a": 1})
    merged = state.with_data(b=2)
    assert merged.data == {"a": 1, "b": 2}
    assert (merged.step_index, merged.step_name) == (3, "build_mesh")


# ---------------------------------------------------------------------------
# What a step declares about the payload
# ---------------------------------------------------------------------------


def _step_classes() -> dict[str, type]:
    import hydromodpy.workflow.steps as steps

    return {name: getattr(steps, name) for name in ALL_STEPS}


@pytest.mark.parametrize("step_name", ALL_STEPS)
def test_a_step_exposes_its_payload_keys_at_runtime(step_name: str) -> None:
    """The runtime half of ``tests/unit/architecture/test_step_payload_keys.py``.

    That gate reads the source; this one reads the built class, so a declaration
    that the AST sees but Python does not - shadowed, or left on a base class -
    fails here.
    """
    cls = _step_classes()[step_name]
    for attribute in ("reads", "writes"):
        declared = getattr(cls, attribute)
        assert isinstance(declared, tuple), f"{step_name}.{attribute}"
        assert all(isinstance(key, str) for key in declared), f"{step_name}.{attribute}"
        assert len(set(declared)) == len(declared), f"{step_name}.{attribute} repeats a key"


def test_no_step_declares_the_payload_classes_that_were_deleted() -> None:
    """``tin`` / ``tout`` are gone; a step carrying one is a half-done rebase."""
    for step_name, cls in _step_classes().items():
        assert not hasattr(cls, "tin"), step_name
        assert not hasattr(cls, "tout"), step_name


def test_standard_step_order_matches_phase_contract() -> None:
    from hydromodpy.workflow.orchestrator import standard_steps
    from hydromodpy.workflow.phases import STANDARD_PIPELINE_STEP_NAMES

    assert tuple(step.name for step in standard_steps()) == STANDARD_PIPELINE_STEP_NAMES
