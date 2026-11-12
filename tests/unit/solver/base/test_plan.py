"""The runtime objects of the solver port: ``RunSlot``, ``SolverRun`` and ``RunContext``."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.solver.base.plan import (
    ProcessRun,
    RunContext,
    RunSlot,
    SimulationPlan,
    SolverRun,
)

RUN = ProcessRun(
    id="flow_main::modflow6", process_id="flow_main", process_type="flow", solver="modflow6"
)
PLAN = SimulationPlan(name="demo", description="demo", runs=(RUN,))


@pytest.mark.parametrize("name", ["", "   "])
def test_a_slot_refuses_a_blank_name(name: str) -> None:
    with pytest.raises(SolverInputError, match="cannot be blank"):
        RunSlot(Path("scratch"), name)


@pytest.mark.parametrize(
    ("value", "member"),
    [
        (RunSlot(Path("scratch"), "island"), "name"),
        (SolverRun(slot=RunSlot(Path("scratch"), "island")), "solved"),
    ],
    ids=["slot", "solver run"],
)
def test_the_slot_and_the_solver_run_are_frozen(value: object, member: str) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, member, "changed")


@pytest.mark.parametrize("given", [-0.1, float("nan")], ids=["negative", "nan"])
def test_a_solver_run_refuses_a_solve_time_that_is_not_a_duration(given: float) -> None:
    with pytest.raises(SolverInputError, match="solve_s is a duration"):
        SolverRun(slot=RunSlot(Path("scratch"), "island"), solve_s=given)


def test_a_solver_run_needs_a_slot() -> None:
    with pytest.raises(TypeError, match="RunSlot"):
        SolverRun(slot=SimpleNamespace(folder=Path("scratch"), name="island"))


def _workflow(**solver_runs: SolverRun) -> WorkflowContext:
    ctx = WorkflowContext(cfg=None, config_path=Path("project.toml"), raw_toml={})
    ctx.execution.solver_runs.update(solver_runs)
    return ctx


def test_a_run_context_carries_no_model_and_no_folder_of_its_own() -> None:
    """What a run produced travels as one ``SolverRun``, not as loose members."""
    members = {field.name for field in dataclasses.fields(RunContext)}

    assert members == {"plan", "run", "state", "store", "solver_run", "upstream"}
