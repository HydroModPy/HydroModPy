"""``run_processing`` solves an auxiliary model only for the start states that ask for one."""

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


class _Package:
    def __init__(self) -> None:
        self.strt = self
        self.heads: list[np.ndarray] = []

    def write(self, *args, **kwargs) -> None:
        del args, kwargs

    def set_data(self, head) -> None:
        self.heads.append(np.asarray(head))


class _Simulation:
    def write_simulation(self, *args, **kwargs) -> None:
        del args, kwargs

    def run_simulation(self, *args, **kwargs):
        del args, kwargs
        return True, None


def _model(initial, regime: str) -> Modflow6:
    model = object.__new__(Modflow6)
    model.sim = _Simulation()
    model.npf = _Package()
    model.ic = _Package()
    model.nper = 1
    model.nlay = 1
    model.ncpl = 2
    model._runtime_dirty_packages = ("npf",)
    model.inputs = make_model(
        initial=initial, time=ModelTime(grid=None, regime=regime, first_period_steady=True)
    )
    return model


@pytest.fixture
def solves(monkeypatch) -> list[str]:
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


CASES = (
    ("a steady start of a transient run", SteadyStart(), "transient", ["steady"], [[[1.0, 2.0]]]),
    (
        "a cyclic start of a transient run",
        CyclicStart(CyclicSpinupStrategy()),
        "transient",
        ["cyclic"],
        [[[3.0, 4.0]]],
    ),
    ("a steady start of a steady run", SteadyStart(), "steady", [], []),
    ("a head rule", HeadRule("top"), "transient", [], []),
    ("a prior state", PriorState(np.zeros((1, 2)), {}, "prior.zarr"), "transient", [], []),
    ("a solved state", SolvedState(np.zeros((1, 2)), "modflow6"), "transient", [], []),
)


@pytest.mark.parametrize(
    ("case", "initial", "regime", "expected_calls", "expected_heads"),
    CASES,
    ids=[case[0] for case in CASES],
)
def test_the_start_state_decides_which_auxiliary_solve_runs(
    solves, case, initial, regime, expected_calls, expected_heads
) -> None:
    del case
    model = _model(initial, regime)

    success = run_module.run_processing(model, ModflowRunOptions(write_model=True, run_model=True))

    assert success is True
    assert solves == expected_calls
    assert [head.tolist() for head in model.ic.heads] == expected_heads


def test_a_run_that_is_not_solved_runs_no_auxiliary_solve(solves) -> None:
    model = _model(SteadyStart(), "transient")

    run_module.run_processing(model, ModflowRunOptions(write_model=True, run_model=False))

    assert solves == []
