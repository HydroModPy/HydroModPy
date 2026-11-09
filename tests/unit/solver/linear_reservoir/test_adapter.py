"""Unit tests of the flow adapter of the linear reservoir backend."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

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


def _one_cell_model(**members: object) -> object:
    """A `Model` of one cell, one daily period, the recharge the binder gives."""
    return make_model(
        geometry=one_cell_geometry(),
        time=ModelTime(grid=time_grid(1.0), regime="transient", first_period_steady=False),
        recharge=FlowRechargeConfig(units="m/s", values=[5.0e-8]),
        **members,
    )


def _slot(tmp_path: object) -> RunSlot:
    return RunSlot(
        folder=tmp_path,
        name="probe",
        stop_before_solve=False,
        bin_dir=None,
        shared_forcing_dir=None,
    )


def test_the_declared_writes_are_the_two_tables_the_store_serves() -> None:
    adapter = LinearReservoirFlowAdapter()
    assert adapter.writes == ("timeseries", "budgets")


def test_the_declared_supports_carry_the_recharge_of_the_run() -> None:
    adapter = LinearReservoirFlowAdapter()
    assert "recharge" in adapter.supports
    assert "steady_start" in adapter.supports


def test_a_table_without_its_time_constant_is_refused() -> None:
    """The memory of the reservoir belongs to the site, so no default exists."""
    adapter = LinearReservoirFlowAdapter()
    with pytest.raises(ValidationError):
        adapter.validate(_one_cell_model(), LinearReservoirOptions(), _slot("/tmp/none"))  # noqa: S108


def test_a_time_constant_read_in_days_and_in_a_written_unit_is_the_same() -> None:
    assert LinearReservoirOptions(time_constant=30.0).time_constant == 30.0
    assert LinearReservoirOptions(time_constant="30 days").time_constant == 30.0


def test_a_mesh_of_two_cells_is_refused() -> None:
    """The backend reads one cell; the mesh the factory gives in default holds six."""
    adapter = LinearReservoirFlowAdapter()
    model = make_model()
    table = LinearReservoirOptions(time_constant=30.0)
    with pytest.raises(SolverInputError):
        adapter.validate(model, table, _slot("/tmp/none"))  # noqa: S108


def test_the_binder_hands_the_native_series_the_adapter_reads() -> None:
    """`NativeSeries` carries one edge more than values, as the binder cuts it."""
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


def test_a_steady_period_integrates_to_tau_r_and_ar(tmp_path) -> None:
    """A period `Model.time` marks steady closes on `s = tau * R`, `Q = A * R`."""
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


def test_locate_cell_answers_the_one_cell_and_nothing_without_an_engine() -> None:
    from types import SimpleNamespace

    adapter = LinearReservoirFlowAdapter()
    solved = SimpleNamespace(solver_model=object())
    assert adapter.locate_cell(solved, 1.0e6, -3.0) == (0, 0, 0)
    assert adapter.top_active_layer(solved, 0, 0) == 0
    assert adapter.locate_cell(SimpleNamespace(solver_model=None), 0.0, 0.0) is None
    with pytest.raises(ValueError):
        adapter.top_active_layer(solved, 0, 1)
