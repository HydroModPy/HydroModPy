"""The runtime objects of the solver port: ``RunSlot``, ``SolverRun`` and ``RunContext``."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.solver.base.plan import RunContext, RunSlot, SolverRun

SLOT = RunSlot(Path("scratch"), "island")

FROZEN = [
    pytest.param(SLOT, "name", id="slot"),
    pytest.param(SolverRun(slot=SLOT), "solved", id="solver run"),
]


@pytest.mark.parametrize("name", ["", "   "], ids=["empty", "blank"])
def test_slot_refuses_a_blank_name(name: str) -> None:
    with pytest.raises(SolverInputError, match="cannot be blank"):
        RunSlot(Path("scratch"), name)


@pytest.mark.parametrize(("value", "member"), FROZEN)
def test_slot_and_solver_run_are_frozen(value: object, member: str) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, member, "changed")


@pytest.mark.parametrize("given", [-0.1, float("nan")], ids=["negative", "nan"])
def test_solve_time_must_be_a_duration(given: float) -> None:
    with pytest.raises(SolverInputError, match="solve_s is a duration"):
        SolverRun(slot=SLOT, solve_s=given)


def test_solver_run_needs_a_slot() -> None:
    with pytest.raises(TypeError, match="RunSlot"):
        SolverRun(slot=SimpleNamespace(folder=Path("scratch"), name="island"))


def test_run_context_members() -> None:
    # What a run produced travels as one SolverRun, not as loose members.
    members = {field.name for field in dataclasses.fields(RunContext)}

    assert members == {"plan", "run", "state", "store", "solver_run", "upstream"}
