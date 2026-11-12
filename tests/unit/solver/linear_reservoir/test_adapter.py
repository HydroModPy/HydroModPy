"""Flow adapter of the linear reservoir: what it declares, refuses and builds for one cell.

The backend reads one cell, one recharge rate (m/s) and one time constant (days).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.model.forcing.native import NativeSeries
from hydromodpy.model.model import ModelTime
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.solver.base.plan import RunSlot
from hydromodpy.solver.linear_reservoir.adapter import (
    LinearReservoirFlowAdapter,
    pieces_of_native_series,
)
from hydromodpy.solver.linear_reservoir.options import LinearReservoirOptions
from tests._helpers.model_factory import make_model, one_cell_geometry, time_grid


def _slot(tmp_path: object) -> RunSlot:
    return RunSlot(
        folder=tmp_path,
        name="probe",
        stop_before_solve=False,
        bin_dir=None,
        shared_forcing_dir=None,
    )


def test_declared_writes() -> None:
    adapter = LinearReservoirFlowAdapter()
    assert adapter.writes == ("discharge", "reservoir_storage", "budgets")


def test_declared_supports() -> None:
    adapter = LinearReservoirFlowAdapter()
    assert "recharge" in adapter.supports
    assert "steady_start" in adapter.supports


def test_refuses_a_mesh_of_several_cells() -> None:
    # The default mesh of the factory holds six cells.
    adapter = LinearReservoirFlowAdapter()
    model = make_model()
    table = LinearReservoirOptions(time_constant=30.0)
    with pytest.raises(SolverInputError):
        adapter.validate(model, table, _slot("/tmp/none"))  # noqa: S108


def test_pieces_of_a_native_series() -> None:
    # A NativeSeries carries one edge more than values, as the binder cuts it.
    one_day = 86400.0
    starts = pd.date_range("2024-01-01", periods=21, freq="D")
    series = NativeSeries(starts=starts, values=np.full(20, 5.0e-8))
    rates, durations, owners = pieces_of_native_series(
        series,
        (one_day, one_day, one_day, one_day),
        time_grid_start=starts[0],
    )
    assert len(rates) == 20
    assert len(owners) == 20


def test_steady_period_closes_on_tau_r(tmp_path) -> None:
    # A steady period closes on s = tau * R and Q = A * R.
    model = make_model(
        geometry=one_cell_geometry(),
        time=ModelTime(grid=time_grid(1.0), regime="transient", first_period_steady=True),
        recharge=FlowRechargeConfig(units="m/s", values=[5.0e-8]),
    )
    table = LinearReservoirOptions(time_constant=30.0)
    adapter = LinearReservoirFlowAdapter()
    solver_run = adapter.build(model, table, _slot(tmp_path))  # noqa: S108
    assert solver_run.solver_model is not None
    states, released = solver_run.solver_model.run()
    tau_seconds = 30.0 * 86400.0
    rate_per_s = 5.0e-8
    assert states[-1] == pytest.approx(tau_seconds * rate_per_s, rel=1e-12)
    # The piece released `A * R * delta` m3 over the period, so the depth the
    # run holds of the release reads `R * delta`: the discharge of the piece
    # that the series of the run writes is `A * R` in m3/s.
    assert released[-1] == pytest.approx(rate_per_s * 86400.0, rel=1e-12)


def test_locate_cell() -> None:
    from types import SimpleNamespace

    adapter = LinearReservoirFlowAdapter()
    solved = SimpleNamespace(solver_model=object())
    assert adapter.locate_cell(solved, 1.0e6, -3.0) == (0, 0, 0)
    assert adapter.top_active_layer(solved, 0, 0) == 0
    assert adapter.locate_cell(SimpleNamespace(solver_model=None), 0.0, 0.0) is None
    with pytest.raises(ValueError):
        adapter.top_active_layer(solved, 0, 1)
