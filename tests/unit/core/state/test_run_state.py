"""The registry of a run and the request a calibration trial puts on its setup.

The ``lightweight`` flag of the registry tells steps 06 and 07 whether to open
the store, write provenance and ingest results. One registry holds the solver runs.
"""

from __future__ import annotations

import dataclasses
import pickle
from pathlib import Path

import pytest

from hydromodpy.core.state.run_state import ExecutionRegistry, SetupContext, SlotRequest


def test_default_registry_is_heavy() -> None:
    reg = ExecutionRegistry()
    assert reg.lightweight is False


def test_lightweight_flag() -> None:
    reg = ExecutionRegistry(lightweight=True)
    assert reg.lightweight is True


def test_lightweight_keeps_solver_runs() -> None:
    reg = ExecutionRegistry(lightweight=True)
    reg.solver_runs["x"] = "solver run"
    assert reg.solver_runs == {"x": "solver run"}
    assert reg.simulation_plan is None


def test_one_registry_of_solver_runs() -> None:
    names = set(vars(ExecutionRegistry()))
    assert "solver_runs" in names
    assert not names & {"models_by_run_id", "output_dirs_by_run_id"}


def test_slot_request_defaults() -> None:
    request = SlotRequest()
    assert (request.name, request.stop_before_solve, request.shared_forcing_dir) == (
        None,
        False,
        None,
    )


def test_slot_request_is_frozen() -> None:
    request = SlotRequest(name="island_trial000001", shared_forcing_dir=Path("shared"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.name = "other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        SlotRequest("island_trial000001")  # type: ignore[misc]


def test_slot_request_pickles() -> None:
    request = SlotRequest(name="t", stop_before_solve=True, shared_forcing_dir=Path("shared"))
    assert pickle.loads(pickle.dumps(request)) == request


def test_setup_context_fields() -> None:
    names = {field.name for field in dataclasses.fields(SetupContext)}
    assert "slot_request" in names
    assert not names & {"flow_runtime_overrides", "mesh_bundle"}
    assert SetupContext().slot_request is None
