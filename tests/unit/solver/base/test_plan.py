"""The runtime objects of the solver port: ``RunSlot``, ``SolverRun`` and ``RunContext``."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.solver.base.plan import ProcessRun, RunContext, RunSlot, SimulationPlan, SolverRun

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


def test_plan_html_table() -> None:
    flow = ProcessRun(
        id="flow::modflow6", process_id="flow", process_type="flow", solver="modflow6"
    )
    transport = ProcessRun(
        id="tr::prt",
        process_id="tr",
        process_type="transport",
        solver="prt",
        depends_on=("flow::modflow6",),
    )

    html = SimulationPlan(
        name="demo", description="two steps", runs=(flow, transport)
    )._repr_html_()

    assert "<code>demo</code>" in html
    assert "two steps" in html
    # No dependency prints a dash, a dependency prints the run id of the upstream.
    assert "<td>&mdash;</td>" in html
    assert "<td>flow::modflow6</td>" in html
    assert html.count("<tr>") == 3  # header and two runs


def test_empty_plan_html() -> None:
    html = SimulationPlan(name="empty", description="")._repr_html_()

    assert "(empty plan)" in html
    assert "<table" not in html
