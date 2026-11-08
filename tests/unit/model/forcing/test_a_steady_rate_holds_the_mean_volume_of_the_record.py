"""A steady period takes the time mean of the record, each period by its length.

``first_clim = "mean"`` and the recharge of the network criterion used to count each
period once, so a short wet February weighed as much as a long dry July. The steady
period then received another volume than the record gives over the same time. On the
monthly Nancon the two means are 0.15 to 0.68 per cent apart, and much further on
periods of very different lengths.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time.coverage import calendar_sample_days
from hydromodpy.core.time.period_aggregation import period_mean_on_index
from hydromodpy.core.time.steady_initialization import single_period_mean_forcing_time_grid
from hydromodpy.core.units import factor_to_m_per_s
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.model.forcing.cells import discretize_fields_on_cells
from hydromodpy.model.forcing.recharge_rates import (
    criterion_mean_recharge,
    forcing_period_rates,
    mean_recharge_m_s,
)
from hydromodpy.model.forcing.stations import period_means
from hydromodpy.model.forcing.steady_periods import (
    apply_first_clim,
    one_period_rate,
    split_net_recharge,
    steady_rate,
)
from hydromodpy.model.forcing.time_alignment import align_forcing_series_to_simulation_window
from hydromodpy.model.model import ModelTime
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.results.derive.stream.geometry import RECHARGE_MOVE_TOLERANCE
from hydromodpy.solver.boussinesq.forcing.common import ForcingCommonMixin
from hydromodpy.solver.boussinesq.forcing.recharge_resolution import RechargeResolutionMixin
from hydromodpy.solver.modflow6.builders.recharge import recharge_to_spd
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter
from hydromodpy.solver.modflow_nwt.nwt.payloads.recharge_etp import (
    apply_first_clim_2d,
    assemble_rch_data,
)
from tests._helpers import forcing_cases as fc
from tests._helpers.mf6_toy_models import toy_model
from tests._helpers.model_factory import make_model
from tests.unit.solver.modflow_nwt._test_forcing_adapter_builders import _build_solver_mesh

pytestmark = pytest.mark.fast

RATES = [1.0, 4.0, 2.0]
DAYS = np.array([31.0, 28.0, 31.0])
LENGTHS_S = DAYS * 86400.0
TIME_MEAN = (31.0 + 112.0 + 62.0) / 90.0
STEADY_FIRST = np.array([True, False, False])


def _modflow6(steady=STEADY_FIRST, recharge=None, first_clim="mean", time_grid=None):
    members = {}
    if time_grid is not None:
        members["time"] = ModelTime(grid=time_grid, regime="transient", first_period_steady=True)
    model = toy_model(**members)
    model.nper = int(np.size(steady))
    model.perlen = LENGTHS_S if model.nper == 3 else np.array([LENGTHS_S.sum()])
    model.ncpl = 2
    model.steady = np.asarray(steady, dtype=bool)
    model.first_clim = first_clim
    model.recharge = RATES if recharge is None else recharge
    return model


class _Boussinesq(RechargeResolutionMixin, ForcingCommonMixin):
    def __init__(self, time_grid: object, *, flow_regime: str = "transient") -> None:
        self.inputs = make_model(
            time=ModelTime(grid=time_grid, regime=flow_regime, first_period_steady=True)
        )
        self.mesh = SimpleNamespace(n_cells=2)


def test_the_steady_rate_gives_the_volume_of_the_record() -> None:
    value = float(steady_rate(RATES, "mean", durations=DAYS))

    assert value == pytest.approx(TIME_MEAN)
    assert value * DAYS.sum() == pytest.approx(np.dot(RATES, DAYS))
    assert value != pytest.approx(np.mean(RATES), rel=1e-3)


def test_the_unit_of_the_lengths_does_not_matter() -> None:
    assert float(steady_rate(RATES, "mean", durations=LENGTHS_S)) == pytest.approx(TIME_MEAN)


@pytest.mark.parametrize(("first_clim", "expected"), [("first", 1.0), (7.0, 7.0)])
def test_the_other_rules_read_no_length(first_clim, expected) -> None:
    assert float(steady_rate(RATES, first_clim, durations=DAYS)) == expected


def test_a_grid_takes_the_time_mean_cell_by_cell() -> None:
    rates = {0: np.array([1.0, 0.0]), 1: np.array([4.0, 1.0]), 2: np.array([2.0, 0.0])}

    out = apply_first_clim(rates, steady=STEADY_FIRST, first_clim="mean", durations=DAYS)

    np.testing.assert_allclose(out[0], [TIME_MEAN, 28.0 / 90.0])
    np.testing.assert_allclose(out[1], rates[1])


def test_the_net_rate_of_a_split_recharge_is_the_time_mean_of_the_net_rates() -> None:
    net = {0: -1.0, 1: 4.0, 2: -2.0}

    recharge, deficit = split_net_recharge(
        net, steady=STEADY_FIRST, first_clim="mean", durations=DAYS
    )

    expected = np.dot(list(net.values()), DAYS) / DAYS.sum()
    assert float(recharge[0]) - float(deficit[0]) == pytest.approx(expected)
    assert float(recharge[0]) == pytest.approx(4.0 * 28.0 / 90.0)


def test_every_solver_gives_the_steady_period_the_same_rate() -> None:
    cfg = FlowRechargeConfig(values=RATES, first_clim="mean", units="m/s")
    adapter = FlowToModflowAdapter(
        model=make_model(
            recharge=cfg,
            active_sinks_sources=("recharge",),
            time=ModelTime(grid=None, regime="transient", first_period_steady=True),
        ),
        solver_mesh=_build_solver_mesh(),
        nper=3,
        steady=STEADY_FIRST,
        period_lengths=LENGTHS_S,
        sink_fill=False,
    )

    boussinesq = _Boussinesq(SimpleNamespace(period_lengths_seconds=tuple(LENGTHS_S)))
    series = boussinesq.recharge_period_series(
        payload=RATES, nper=3, first_clim="mean", label="recharge"
    )

    assert float(recharge_to_spd(_modflow6())[0][0]) == pytest.approx(TIME_MEAN)
    assert adapter._build_recharge_payload()[0] == pytest.approx(TIME_MEAN)
    np.testing.assert_allclose(series, [TIME_MEAN, 4.0, 2.0])


def test_the_grids_of_every_solver_take_the_time_mean() -> None:
    grids = {k: np.full(2, value) for k, value in enumerate(RATES)}
    boussinesq = _Boussinesq(SimpleNamespace(period_lengths_seconds=tuple(LENGTHS_S)))

    nwt = apply_first_clim_2d(
        raw_arrays=grids,
        first_clim="mean",
        steady=STEADY_FIRST,
        nper=3,
        nrow=1,
        ncol=2,
        durations=LENGTHS_S,
    )
    bsq = boussinesq.apply_first_clim_to_cellwise_recharge(
        raw_arrays=grids, nper=3, first_clim="mean"
    )

    np.testing.assert_allclose(recharge_to_spd(_modflow6(recharge=grids))[0], TIME_MEAN)
    np.testing.assert_allclose(nwt[0], TIME_MEAN)
    np.testing.assert_allclose(bsq[0], TIME_MEAN)


def test_a_time_grid_of_one_period_keeps_the_lengths_of_its_source() -> None:
    grid = single_period_mean_forcing_time_grid(
        SimpleNamespace(period_lengths_seconds=tuple(LENGTHS_S))
    )

    assert grid.period_lengths_seconds.tolist() == [LENGTHS_S.sum()]
    np.testing.assert_allclose(grid.record_lengths_seconds, LENGTHS_S)
    alone = SimpleNamespace(period_lengths_seconds=(LENGTHS_S[0],))
    assert single_period_mean_forcing_time_grid(alone).record_lengths_seconds is None


def test_the_auxiliary_steady_solve_of_every_solver_reads_the_time_mean() -> None:
    grid = single_period_mean_forcing_time_grid(
        SimpleNamespace(period_lengths_seconds=tuple(LENGTHS_S))
    )

    model = _modflow6(steady=[True], recharge=np.array(RATES), time_grid=grid)
    boussinesq = _Boussinesq(grid, flow_regime="steady")
    nwt = assemble_rch_data(
        payload=RATES,
        first_clim="mean",
        steady=np.array([True]),
        nper=1,
        durations=grid.period_lengths_seconds,
        record_lengths=grid.record_lengths_seconds,
    )

    assert float(recharge_to_spd(model)[0][0]) == pytest.approx(TIME_MEAN)
    assert nwt[0] == pytest.approx(TIME_MEAN)
    assert boussinesq.recharge_period_series(
        payload=RATES, nper=1, first_clim="mean", label="recharge"
    ).tolist() == pytest.approx([TIME_MEAN])


def test_a_record_without_lengths_counts_each_value_once() -> None:
    assert one_period_rate(RATES, steady=True, first_clim="mean") == pytest.approx(7.0 / 3.0)
    assert one_period_rate(RATES, steady=True, first_clim="first", durations=DAYS) == 1.0


@pytest.mark.parametrize(
    "durations",
    [[31.0, 28.0], [31.0, 0.0, 31.0], [31.0, -1.0, 31.0], [31.0, np.nan, 31.0]],
)
def test_a_length_that_is_not_one_positive_number_per_rate_is_refused(durations) -> None:
    with pytest.raises(ValueError, match="period length"):
        steady_rate(RATES, "mean", durations=durations)


def test_a_table_with_a_period_beyond_the_lengths_is_refused() -> None:
    with pytest.raises(ValueError, match="has no length"):
        apply_first_clim({0: 1.0, 3: 2.0}, steady=[True], first_clim="mean", durations=DAYS)


def test_the_criterion_reads_the_same_mean_as_the_steady_period() -> None:
    model = _modflow6()
    steady = float(recharge_to_spd(model)[0][0])

    assert mean_recharge_m_s(model) == pytest.approx(steady)


def test_the_criterion_weighs_the_periods_of_a_grid_like_its_cells() -> None:
    mesh = SimpleNamespace(cell_areas=lambda: np.array([1.0, 3.0]))
    grids = {k: np.array([value, value]) for k, value in enumerate(RATES)}

    model = SimpleNamespace(recharge=grids, solver_mesh=mesh, perlen=LENGTHS_S)

    assert mean_recharge_m_s(model) == pytest.approx(TIME_MEAN)


def test_a_record_the_criterion_cannot_date_counts_each_value_once() -> None:
    assert mean_recharge_m_s(SimpleNamespace(recharge=[1.0, 4.0, 1.0])) == pytest.approx(2.0)
    assert mean_recharge_m_s(
        SimpleNamespace(recharge=[1.0, 4.0, 1.0], perlen=np.array([86400.0]))
    ) == pytest.approx(2.0)
    assert criterion_mean_recharge([1.0, 3.0]) == 2.0


def test_a_period_without_a_finite_rate_loses_its_length_too() -> None:
    assert criterion_mean_recharge([1.0, np.nan, 3.0], durations=[1.0, 50.0, 3.0]) == 2.5
    with pytest.raises(ValueError, match="2 recharge entries need 2 lengths"):
        criterion_mean_recharge([1.0, 3.0], durations=[1.0])


MONTH_ENDS = pd.DatetimeIndex(["2000-01-31", "2000-02-29", "2000-03-31"])
MONTH_STARTS = pd.DatetimeIndex(["2000-01-01", "2000-02-01", "2000-03-01"])
MONTH_RATES = np.array([2.0, 8.0, 1.0])
MONTH_DAYS = np.array([31.0, 29.0, 31.0])
MONTH_TIME_MEAN = float(np.average(MONTH_RATES, weights=MONTH_DAYS))


ONE_PERIOD = (pd.Timestamp("2000-01-01"), pd.Timestamp("2000-04-01"))
ONE_PERIOD_WINDOW = fc.window("2000-01-01", "2000-03-31", period_bounds=(ONE_PERIOD,))


@pytest.mark.parametrize(
    ("stamps", "expected"),
    [
        (MONTH_ENDS, MONTH_DAYS),
        (MONTH_STARTS, MONTH_DAYS),
        (pd.DatetimeIndex(["2000-01-15", "2000-02-15"]), [31.0, 29.0]),
        (
            pd.DatetimeIndex(["2000-01-01", "2000-02-01", "2000-04-01", "2000-05-01"]),
            [31, 29, 30, 31],
        ),
        (pd.DatetimeIndex(["2000-12-31", "2001-12-31"]), [366.0, 365.0]),
        (pd.DatetimeIndex(["2000-01-01", "2001-01-01", "2003-01-01"]), [366.0, 365.0, 365.0]),
    ],
)
def test_a_calendar_record_counts_each_sample_by_its_month_or_year(stamps, expected) -> None:
    np.testing.assert_allclose(calendar_sample_days(stamps), expected)


@pytest.mark.parametrize(
    "stamps",
    [
        pd.date_range("2000-01-01", periods=60, freq="D"),
        pd.date_range("2000-01-01", periods=9, freq="7D"),
        pd.date_range("2000-01-01", periods=5, freq="40D"),
        pd.DatetimeIndex(["2000-01-15", "2000-03-15"]),
        pd.DatetimeIndex(["2000-01-31"]),
    ],
)
def test_any_other_record_keeps_equal_weights(stamps) -> None:
    assert calendar_sample_days(stamps) is None


@pytest.mark.parametrize("stamps", [MONTH_ENDS, MONTH_STARTS])
def test_a_series_on_one_period_takes_the_time_mean(stamps) -> None:
    aligned = align_forcing_series_to_simulation_window(
        pd.Series(MONTH_RATES, index=stamps), simulation_window=ONE_PERIOD_WINDOW
    )

    assert float(aligned.iloc[0]) == pytest.approx(MONTH_TIME_MEAN)


def test_a_sample_alone_in_its_period_keeps_its_exact_value() -> None:
    aligned = align_forcing_series_to_simulation_window(
        pd.Series(MONTH_RATES, index=MONTH_ENDS),
        simulation_window=fc.window("2000-01-01", "2000-03-31"),
    )

    assert aligned.tolist() == MONTH_RATES.tolist()


def test_a_station_on_one_period_takes_the_time_mean() -> None:
    values = period_means(
        pd.Series(MONTH_RATES, index=MONTH_ENDS),
        period_bounds=[ONE_PERIOD],
        coverage_policy="error",
        label="station",
    )

    assert values.tolist() == pytest.approx([MONTH_TIME_MEAN])


def test_a_grid_on_one_period_takes_the_time_mean() -> None:
    x, y = fc.pixel_axes(2, 2)
    stack = np.stack([np.full((2, 2), rate) for rate in MONTH_RATES])
    record = fc.field_record(fc.grid_dataset(stack, x, y, MONTH_ENDS))

    arrays = discretize_fields_on_cells(
        load_result=LoadResult(fields=[record]),
        centers=np.array([[x[0], y[0]]]),
        nper=1,
        simulation_window=ONE_PERIOD_WINDOW,
        mesh_crs=None,
    )

    assert float(arrays[0][0]) == pytest.approx(MONTH_TIME_MEAN * factor_to_m_per_s("mm/day"))


def test_the_period_mean_of_the_criterion_takes_the_time_mean() -> None:
    series = pd.Series(MONTH_RATES, index=MONTH_ENDS)

    with_start = period_mean_on_index(series, pd.DatetimeIndex(["2000-04-01"]), start="2000-01-01")
    alone = period_mean_on_index(series, pd.DatetimeIndex(["2000-04-01"]))

    assert float(with_start.iloc[0]) == pytest.approx(MONTH_TIME_MEAN)
    assert float(alone.iloc[0]) == pytest.approx(MONTH_TIME_MEAN)


def test_a_steady_phase_and_a_monthly_phase_read_one_recharge() -> None:
    """The by-hand calibration: a move here logs a change of data that never came."""
    samples = pd.Series(MONTH_RATES, index=MONTH_ENDS)
    whole = pd.DatetimeIndex(["2000-01-01", "2000-04-01"])
    months = pd.DatetimeIndex(["2000-01-01", "2000-02-01", "2000-03-01", "2000-04-01"])

    steady = criterion_mean_recharge(list(forcing_period_rates(samples, whole)))
    monthly = criterion_mean_recharge(
        list(forcing_period_rates(samples, months)),
        durations=(months[1:] - months[:-1]).total_seconds().to_numpy(),
    )

    assert np.isclose(steady, monthly, rtol=RECHARGE_MOVE_TOLERANCE, atol=0.0)
    assert steady == pytest.approx(MONTH_TIME_MEAN)
