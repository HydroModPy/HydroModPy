"""Flow adapter of the linear reservoir: what it declares, refuses and builds for one cell.

The backend reads one cell, one recharge rate (m/s) and one time constant (days).
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.contracts.observables import ObservableRequest
from hydromodpy.core.exceptions import ObservableNotAvailableError, SolverInputError
from hydromodpy.model.forcing.native import NativeSeries
from hydromodpy.model.model import ModelTime
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.solver.base.plan import WATER_BUDGET_METRIC, RunSlot, SolverRun
from hydromodpy.solver.linear_reservoir.adapter import (
    LinearReservoirFlowAdapter,
    pieces_of,
    pieces_of_native_series,
    steady_rate_m_per_s,
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


DAY_S = 86400.0
EDGES = pd.date_range("2024-01-01", periods=3, freq="D")


def grid_of(*days: float) -> SimpleNamespace:
    return SimpleNamespace(period_lengths_seconds=np.array(days) * DAY_S)


def model_of(grid, recharge, native=None) -> SimpleNamespace:
    return SimpleNamespace(
        time=SimpleNamespace(grid=grid), recharge=recharge, native_recharge=native
    )


PIECES = [
    pytest.param(
        grid_of(1.0, 2.0),
        SimpleNamespace(values={0: 2.0e-8, 1: 4.0e-8}, units="m/s"),
        ((2.0e-8, 4.0e-8), (DAY_S, 2 * DAY_S)),
        id="rates keyed by period",
    ),
    pytest.param(
        grid_of(1.0, 1.0),
        SimpleNamespace(values=[1.0, 2.0], units="mm/day"),
        ((1.0e-3 / DAY_S, 2.0e-3 / DAY_S), (DAY_S, DAY_S)),
        id="rates in mm per day",
    ),
]


@pytest.mark.parametrize(("grid", "recharge", "expected"), PIECES)
def test_pieces_of_a_period_recharge(grid, recharge, expected) -> None:
    rates, durations, owners = pieces_of(model_of(grid, recharge))

    np.testing.assert_allclose(rates, expected[0], rtol=1e-12)
    np.testing.assert_allclose(durations, expected[1], rtol=1e-12)
    assert owners == (0, 1)


PIECE_REFUSALS = [
    pytest.param(model_of(None, None), "carries no time grid", id="no time grid"),
    pytest.param(model_of(grid_of(1.0), None), "carries none", id="no recharge"),
    pytest.param(
        model_of(grid_of(1.0, 1.0), SimpleNamespace(values=[1.0e-8], units="m/s")),
        "1 rates for 2 periods",
        id="one rate for two periods",
    ),
    pytest.param(
        model_of(
            grid_of(1.0, 1.0),
            None,
            SimpleNamespace(starts=EDGES[:2], values=np.array([1.0e-8, 1.0e-8])),
        ),
        "2 values: one more edge",
        id="native edges missing",
    ),
    pytest.param(
        model_of(
            grid_of(1.0, 1.0),
            None,
            SimpleNamespace(starts=EDGES, values=np.array([1.0e-8, -2.0e-8])),
        ),
        "negative at native step 1",
        id="negative native recharge",
    ),
]


@pytest.mark.parametrize(("model", "message"), PIECE_REFUSALS)
def test_pieces_refusals(model, message) -> None:
    with pytest.raises(SolverInputError, match=message):
        pieces_of(model)


def test_steady_rate_of_a_native_series() -> None:
    # 1 day at 2e-8 and 3 days at 6e-8 m/s: (2 + 18) / 4 = 5e-8 m/s.
    starts = pd.DatetimeIndex(["2024-01-01", "2024-01-02", "2024-01-05"])
    series = NativeSeries(starts=starts, values=[2.0e-8, 6.0e-8])
    model = make_model(
        geometry=one_cell_geometry(),
        time=ModelTime(grid=time_grid(4.0), regime="steady", first_period_steady=True),
        native_recharge=series,
    )

    assert steady_rate_m_per_s(model) == pytest.approx(5.0e-8, rel=1e-12)


STEADY_RATES = [
    pytest.param(None, 0.0, id="no recharge"),
    pytest.param(
        FlowRechargeConfig(units="m/s", values={0: 2.0e-8, 1: 6.0e-8}), 4.0e-8, id="keyed"
    ),
    pytest.param(SimpleNamespace(values=None, units="m/s"), 0.0, id="no values"),
]


@pytest.mark.parametrize(("recharge", "expected"), STEADY_RATES)
def test_steady_rate_of_a_period_recharge(recharge, expected) -> None:
    model = make_model(
        geometry=one_cell_geometry(),
        time=ModelTime(grid=time_grid(1.0, 1.0), regime="transient", first_period_steady=True),
        recharge=recharge,
    )

    assert steady_rate_m_per_s(model) == pytest.approx(expected, abs=1e-20)


def solved_run(tmp_path, recharge_m_s: float) -> tuple[LinearReservoirFlowAdapter, SolverRun]:
    model = make_model(
        geometry=one_cell_geometry(),
        time=ModelTime(grid=time_grid(1.0, 1.0), regime="transient", first_period_steady=False),
        recharge=FlowRechargeConfig(units="m/s", values=[recharge_m_s, recharge_m_s]),
    )
    adapter = LinearReservoirFlowAdapter()
    built = adapter.build(model, LinearReservoirOptions(time_constant=30.0), _slot(tmp_path))
    return adapter, adapter.run(built)


def test_solved_run_closes_its_budget(tmp_path) -> None:
    _, solved = solved_run(tmp_path, 5.0e-8)

    assert solved.solved
    assert solved.metrics[WATER_BUDGET_METRIC] == pytest.approx(0.0, abs=1e-9)  # percent


def test_run_without_recharge_has_no_discrepancy(tmp_path) -> None:
    # Nothing fell and nothing was stored: the percent has no scale and reads 0.
    _, solved = solved_run(tmp_path, 0.0)

    assert solved.metrics[WATER_BUDGET_METRIC] == 0.0


OBSERVED = [
    pytest.param("domain", None, "discharge", "m3 s-1", id="discharge on the domain"),
    pytest.param("cell", (0, 0, 0), "reservoir_storage", "m", id="storage on the one cell"),
]


@pytest.mark.parametrize(("support", "cell", "name", "units"), OBSERVED)
def test_observables_of_a_run(tmp_path, support, cell, name, units) -> None:
    adapter, solved = solved_run(tmp_path, 5.0e-8)
    request = ObservableRequest(id="r", name=name, support=support, cell=cell)

    result = adapter.observables(solved, [request])["r"]

    assert result.units == units
    assert result.values.shape == (2,)


def test_discharge_at_equilibrium(tmp_path) -> None:
    # The run starts on the steady state of its recharge, so the cell drains what falls.
    adapter, solved = solved_run(tmp_path, 5.0e-8)
    request = ObservableRequest(id="q", name="discharge", support="domain")

    values = adapter.observables(solved, [request])["q"].values

    np.testing.assert_allclose(values, 5.0e-8 * 1.0e6, rtol=1e-9)  # m3/s, A * R


def test_no_request_serves_nothing(tmp_path) -> None:
    adapter, solved = solved_run(tmp_path, 5.0e-8)

    assert adapter.observables(solved, []) == {}


OBSERVABLE_REFUSALS = [
    pytest.param(
        ObservableRequest(id="c", name="discharge", support="cell", cell=(0, 1, 0)),
        "asks cell",
        id="another cell",
    ),
    pytest.param(
        ObservableRequest(id="b", name="discharge", support="boundary", key="x"),
        "asks support 'boundary'",
        id="a boundary",
    ),
    pytest.param(
        ObservableRequest(id="h", name="head", support="domain"),
        "does not produce observable 'head'",
        id="a head",
    ),
]


@pytest.mark.parametrize(("request_", "message"), OBSERVABLE_REFUSALS)
def test_observable_refusals(tmp_path, request_, message) -> None:
    adapter, solved = solved_run(tmp_path, 5.0e-8)

    with pytest.raises(ObservableNotAvailableError, match=message):
        adapter.observables(solved, [request_])


def test_observables_need_an_output(tmp_path) -> None:
    adapter, solved = solved_run(tmp_path, 5.0e-8)
    request = ObservableRequest(id="r", name="discharge", support="domain")

    with pytest.raises(ObservableNotAvailableError, match="No solver output recorded"):
        adapter.observables(SolverRun(slot=solved.slot), [request])


VALIDATION_REFUSALS = [
    pytest.param(
        SimpleNamespace(geometry=None),
        LinearReservoirOptions(time_constant=30.0),
        "no planar cell mesh",
        id="no cell mesh",
    ),
    pytest.param(
        make_model(geometry=one_cell_geometry()),
        SimpleNamespace(time_constant=None),
        "time_constant is required",
        id="no time constant",
    ),
]


@pytest.mark.parametrize(("model", "options", "message"), VALIDATION_REFUSALS)
def test_validation_refusals(tmp_path, model, options, message) -> None:
    with pytest.raises(SolverInputError, match=message):
        LinearReservoirFlowAdapter().validate(model, options, _slot(tmp_path))


def test_run_without_engine_is_refused(tmp_path) -> None:
    unbuilt = SolverRun(slot=_slot(tmp_path))

    with pytest.raises(SolverInputError, match="build it again"):
        LinearReservoirFlowAdapter().run(unbuilt)


def test_no_engine_has_no_top_layer() -> None:
    unbuilt = SimpleNamespace(solver_model=None)

    assert LinearReservoirFlowAdapter().top_active_layer(unbuilt, 0, 0) is None
