"""Unit tests for the typed pipeline state hierarchy."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.pipeline import (
    DerivedState,
    ExportedState,
    ExtractedState,
    LoadedState,
    MeshedState,
    OpenStoreState,
    PipelineState,
    ResolvedState,
    SetupState,
    SolverRanState,
    ValidatedState,
)


# ---------------------------------------------------------------------------
# Inheritance chain
# ---------------------------------------------------------------------------


def test_state_inheritance_chain_is_linear() -> None:
    assert issubclass(ResolvedState, ValidatedState)
    assert issubclass(LoadedState, ResolvedState)
    assert issubclass(MeshedState, LoadedState)
    assert issubclass(SetupState, MeshedState)
    assert issubclass(OpenStoreState, SetupState)
    assert issubclass(SolverRanState, OpenStoreState)
    assert issubclass(ExtractedState, SolverRanState)
    assert issubclass(DerivedState, ExtractedState)
    assert issubclass(ExportedState, DerivedState)


def test_validated_state_holds_config_and_workspace() -> None:
    payload = ValidatedState(config=object(), workspace=Path("/tmp/work"))
    assert payload.workspace == Path("/tmp/work")


def test_resolved_state_extends_validated_with_plans() -> None:
    payload = ResolvedState(
        config=object(),
        workspace=Path("/tmp/w"),
        data_plan=None,
        sim_plan=None,
    )
    # IS-A check confirms inheritance is real, not just structural.
    assert isinstance(payload, ValidatedState)


# ---------------------------------------------------------------------------
# Frozen dataclass behaviour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls",
    [
        ValidatedState,
        ResolvedState,
        LoadedState,
        MeshedState,
        SetupState,
        OpenStoreState,
        SolverRanState,
        ExtractedState,
        DerivedState,
        ExportedState,
    ],
)
def test_typed_states_are_frozen(cls) -> None:
    payload = cls(config=object())
    with pytest.raises(Exception):
        payload.config = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PipelineState as a generic wrapper
# ---------------------------------------------------------------------------


def test_pipeline_state_carries_typed_payload() -> None:
    payload = ValidatedState(config={"k": 1}, workspace=Path("/tmp/w"))
    state: PipelineState[ValidatedState] = PipelineState(run_id="r", data=payload)
    assert state.data is payload
    assert state.data.workspace == Path("/tmp/w")


def test_pipeline_state_advance_with_typed_payload() -> None:
    v = ValidatedState(config="cfg", workspace=Path("/w"))
    r = ResolvedState(config="cfg", workspace=Path("/w"), data_plan="dp")
    state: PipelineState[ValidatedState] = PipelineState(run_id="r", data=v)
    advanced = state.advance(step_index=1, step_name="resolve", data=r)
    assert advanced.data is r
    assert advanced.step_name == "resolve"
    assert advanced.run_id == "r"


def test_pipeline_state_typed_payload_rejects_kwarg_merge() -> None:
    payload = ValidatedState(config="c", workspace=None)
    state: PipelineState[ValidatedState] = PipelineState(run_id="r", data=payload)
    with pytest.raises(TypeError):
        # Cannot merge **extra into a non-mapping payload.
        state.advance(step_index=1, step_name="x", foo="bar")


def test_pipeline_state_get_reads_attribute_for_typed_payload() -> None:
    payload = ValidatedState(config="cfg", workspace=Path("/w"))
    state: PipelineState[ValidatedState] = PipelineState(run_id="r", data=payload)
    assert state.get("workspace") == Path("/w")
    assert state.get("missing", "default") == "default"


# ---------------------------------------------------------------------------
# Backwards-compatible Mapping payload
# ---------------------------------------------------------------------------


def test_pipeline_state_mapping_payload_still_supported() -> None:
    state: PipelineState[dict[str, int]] = PipelineState(run_id="r", data={"counter": 0})
    nxt = state.advance(step_index=1, step_name="x", counter=5)
    assert nxt.data == {"counter": 5}


# ---------------------------------------------------------------------------
# Step tin/tout class attributes wired in step modules
# ---------------------------------------------------------------------------


def test_each_step_class_declares_tin_tout() -> None:
    from hydromodpy.pipeline.steps import (
        BuildGeographicStep,
        BuildMeshStep,
        DeriveStep,
        ExportStep,
        ExtractStep,
        LoadDataStep,
        PrepareSolverStep,
        ResolveStep,
        RunSolverStep,
        SetupProcessStep,
        ValidateStep,
    )

    expected = [
        (ValidateStep, None, ValidatedState),
        (ResolveStep, ValidatedState, ResolvedState),
        (LoadDataStep, ResolvedState, LoadedState),
        (BuildGeographicStep, LoadedState, MeshedState),
        (BuildMeshStep, MeshedState, MeshedState),
        (SetupProcessStep, MeshedState, SetupState),
        (PrepareSolverStep, SetupState, OpenStoreState),
        (RunSolverStep, OpenStoreState, SolverRanState),
        (ExtractStep, SolverRanState, ExtractedState),
        (DeriveStep, ExtractedState, DerivedState),
        (ExportStep, DerivedState, ExportedState),
    ]
    for cls, tin, tout in expected:
        assert getattr(cls, "tin") is tin, f"{cls.__name__}.tin"
        assert getattr(cls, "tout") is tout, f"{cls.__name__}.tout"
