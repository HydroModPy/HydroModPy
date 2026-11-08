"""Unit tests for the registries and the requests of ``hydromodpy.core.state.run_state``.

Covers the ``lightweight`` flag of :class:`ExecutionRegistry` - the flag is
what step 06 / step 07 read to decide whether to open the store, write
provenance, and ingest run results - its one registry of solver runs, and the
:class:`SlotRequest` a calibration trial puts on the setup.
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


def test_lightweight_flag_is_propagated() -> None:
    reg = ExecutionRegistry(lightweight=True)
    assert reg.lightweight is True


def test_lightweight_flag_does_not_affect_the_solver_runs() -> None:
    reg = ExecutionRegistry(lightweight=True)
    reg.solver_runs["x"] = "solver run"
    assert reg.solver_runs == {"x": "solver run"}
    assert reg.simulation_plan is None


def test_one_registry_holds_what_each_run_produced() -> None:
    """The model and the folder of a run travel together, in one ``SolverRun``."""
    names = set(vars(ExecutionRegistry()))
    assert "solver_runs" in names
    assert not names & {"models_by_run_id", "output_dirs_by_run_id"}


def test_a_slot_request_asks_for_nothing_by_default() -> None:
    request = SlotRequest()
    assert (request.name, request.stop_before_solve, request.shared_forcing_dir) == (
        None,
        False,
        None,
    )


def test_a_slot_request_is_frozen_and_named_by_keyword() -> None:
    request = SlotRequest(name="island_trial000001", shared_forcing_dir=Path("shared"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.name = "other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        SlotRequest("island_trial000001")  # type: ignore[misc]


def test_a_slot_request_crosses_a_process_boundary() -> None:
    """A trial forked into a worker carries its request with its setup."""
    request = SlotRequest(name="t", stop_before_solve=True, shared_forcing_dir=Path("shared"))
    assert pickle.loads(pickle.dumps(request)) == request


def test_the_setup_carries_a_slot_request_and_no_untyped_overrides() -> None:
    names = {field.name for field in dataclasses.fields(SetupContext)}
    assert "slot_request" in names
    assert not names & {"flow_runtime_overrides", "mesh_bundle"}
    assert SetupContext().slot_request is None
