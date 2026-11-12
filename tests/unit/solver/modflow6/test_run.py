"""``run_processing`` of MODFLOW 6 solves an auxiliary model only for start states that ask for one.

A steady or cyclic start of a transient run solves first and sets the heads of the IC package.
Other start states, and a steady run, solve nothing.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.model.initial.state import (
    CyclicSpinupStrategy,
    CyclicStart,
    HeadRule,
    PriorState,
    SolvedState,
    SteadyStart,
)
from hydromodpy.model.model import ModelTime
from hydromodpy.solver.modflow6 import run as run_module
from hydromodpy.solver.modflow6.modflow6 import Modflow6
from hydromodpy.solver.modflow_common.options import ModflowRunOptions
from tests._helpers.model_factory import make_model


class Package:
    """An IC or NPF package that records the heads set on it."""

    def __init__(self) -> None:
        self.strt = self
        self.heads: list[np.ndarray] = []

    def write(self, *args, **kwargs) -> None:
        del args, kwargs

    def set_data(self, head) -> None:
        self.heads.append(np.asarray(head))


class Simulation:
    def write_simulation(self, *args, **kwargs) -> None:
        del args, kwargs

    def run_simulation(self, *args, **kwargs):
        del args, kwargs
        return True, None


def two_cell_model(initial, regime: str) -> Modflow6:
    model = object.__new__(Modflow6)
    model.sim = Simulation()
    model.npf = Package()
    model.ic = Package()
    model.nper = 1
    model.nlay = 1
    model.ncpl = 2
    model.inputs = make_model(
        initial=initial, time=ModelTime(grid=None, regime=regime, first_period_steady=True)
    )
    return model


@pytest.fixture
def solves(monkeypatch) -> list[str]:
    """Names of the auxiliary solves that ran. The steady one gives 1, 2 m, the cyclic 3, 4 m."""
    calls: list[str] = []

    def steady(model, *, verbose):
        calls.append("steady")
        return np.array([[1.0, 2.0]])

    def cyclic(model, *, verbose):
        calls.append("cyclic")
        return np.array([[3.0, 4.0]]), 2, True

    monkeypatch.setattr(run_module, "run_modflow6_steady_state_initialization", steady)
    monkeypatch.setattr(run_module, "run_modflow6_cyclic_spinup", cyclic)
    return calls


AUXILIARY_SOLVES = [
    pytest.param(SteadyStart(), "transient", ["steady"], [[[1.0, 2.0]]], id="steady start"),
    pytest.param(
        CyclicStart(CyclicSpinupStrategy()), "transient", ["cyclic"], [[[3.0, 4.0]]], id="cyclic"
    ),
    pytest.param(SteadyStart(), "steady", [], [], id="steady start of a steady run"),
    pytest.param(HeadRule("top"), "transient", [], [], id="head rule"),
    pytest.param(PriorState(np.zeros((1, 2)), {}, "prior.zarr"), "transient", [], [], id="prior"),
    pytest.param(SolvedState(np.zeros((1, 2)), "modflow6"), "transient", [], [], id="solved"),
]


@pytest.mark.parametrize(("initial", "regime", "calls", "heads"), AUXILIARY_SOLVES)
def test_start_state_picks_the_solve(solves, initial, regime, calls, heads) -> None:
    model = two_cell_model(initial, regime)

    success = run_module.run_processing(model, ModflowRunOptions(write_model=True, run_model=True))

    assert success is True
    assert solves == calls
    assert [head.tolist() for head in model.ic.heads] == heads


def test_no_solve_without_a_model_run(solves) -> None:
    model = two_cell_model(SteadyStart(), "transient")

    run_module.run_processing(model, ModflowRunOptions(write_model=True, run_model=False))

    assert solves == []
