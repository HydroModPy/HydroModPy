"""Recharge records reach every solver the same way, in the unit of the record or in m/s.

A steady period takes the length-weighted time mean of its record, a negative first_clim is a
deficit (MODFLOW) or a refusal (Boussinesq), and a table {period: rate} states every period.
Month and year records are dated by the calendar, so a month counts by its days.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time.coverage import calendar_sample_days
from hydromodpy.core.time.period_aggregation import period_mean_on_index
from hydromodpy.core.time.steady_initialization import single_period_mean_forcing_time_grid
from hydromodpy.model.forcing.recharge_rates import mean_recharge_m_s
from hydromodpy.model.forcing.time_alignment import align_forcing_series_to_simulation_window
from hydromodpy.model.model import ModelTime
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.solver.boussinesq.forcing.common import ForcingCommonMixin
from hydromodpy.solver.boussinesq.forcing.recharge_resolution import RechargeResolutionMixin
from hydromodpy.solver.modflow6.builders.recharge import recharge_to_spd
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter
from hydromodpy.solver.modflow_nwt.nwt.payloads.recharge_etp import (
    apply_first_clim_2d,
    assemble_rch_data,
    extract_negative_recharge_evt_payload,
)
from tests._helpers import forcing_cases as fc
from tests._helpers.mf6_toy_models import toy_model
from tests._helpers.model_factory import make_model
from tests.unit.solver.modflow_nwt._test_forcing_adapter_builders import _build_solver_mesh

pytestmark = pytest.mark.fast

RATES = [1.0, 4.0, 2.0]
DAYS = np.array([31.0, 28.0, 31.0])
LENGTHS_S = DAYS * 86400.0
TIME_MEAN = (31.0 + 112.0 + 62.0) / 90.0  # (1 x 31 + 4 x 28 + 2 x 31) / 90 days
STEADY_FIRST = np.array([True, False, False])
LABEL = "flow.sinks_sources.recharge.values"


def modflow6(steady=STEADY_FIRST, recharge=None, time_grid=None):
    members = {}
    if time_grid is not None:
        members["time"] = ModelTime(grid=time_grid, regime="transient", first_period_steady=True)
    model = toy_model(**members)
    model.nper = int(np.size(steady))
    model.perlen = LENGTHS_S if model.nper == 3 else np.array([LENGTHS_S.sum()])
    model.ncpl = 2
    model.steady = np.asarray(steady, dtype=bool)
    model.first_clim = "mean"
    model.recharge = RATES if recharge is None else recharge
    return model


class Boussinesq(RechargeResolutionMixin, ForcingCommonMixin):
    def __init__(self, time_grid=None, *, regime="transient", first_period_steady=True, **members):
        self.inputs = make_model(
            time=ModelTime(grid=time_grid, regime=regime, first_period_steady=first_period_steady),
            **members,
        )
        self.mesh = SimpleNamespace(n_cells=2)


def source_grid() -> SimpleNamespace:
    return SimpleNamespace(period_lengths_seconds=tuple(LENGTHS_S))


def test_solvers_agree_on_steady_rate():
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
    series = Boussinesq(source_grid()).recharge_period_series(
        payload=RATES, nper=3, first_clim="mean", label="recharge"
    )

    assert float(recharge_to_spd(modflow6())[0][0]) == pytest.approx(TIME_MEAN)
    assert adapter._build_recharge_payload()[0] == pytest.approx(TIME_MEAN)
    np.testing.assert_allclose(series, [TIME_MEAN, 4.0, 2.0])


def test_solvers_agree_on_grids():
    grids = {k: np.full(2, value) for k, value in enumerate(RATES)}

    nwt = apply_first_clim_2d(
        raw_arrays=grids,
        first_clim="mean",
        steady=STEADY_FIRST,
        nper=3,
        nrow=1,
        ncol=2,
        durations=LENGTHS_S,
    )
    bsq = Boussinesq(source_grid()).apply_first_clim_to_cellwise_recharge(
        raw_arrays=grids, nper=3, first_clim="mean"
    )

    np.testing.assert_allclose(recharge_to_spd(modflow6(recharge=grids))[0], TIME_MEAN)
    np.testing.assert_allclose(nwt[0], TIME_MEAN)
    np.testing.assert_allclose(bsq[0], TIME_MEAN)


def test_one_period_grid_keeps_lengths():
    grid = single_period_mean_forcing_time_grid(source_grid())

    assert grid.period_lengths_seconds.tolist() == [LENGTHS_S.sum()]
    np.testing.assert_allclose(grid.record_lengths_seconds, LENGTHS_S)
    alone = SimpleNamespace(period_lengths_seconds=(LENGTHS_S[0],))
    assert single_period_mean_forcing_time_grid(alone).record_lengths_seconds is None


def test_auxiliary_steady_time_mean():
    grid = single_period_mean_forcing_time_grid(source_grid())
    model = modflow6(steady=[True], recharge=np.array(RATES), time_grid=grid)
    nwt = assemble_rch_data(
        payload=RATES,
        first_clim="mean",
        steady=np.array([True]),
        nper=1,
        durations=grid.period_lengths_seconds,
        record_lengths=grid.record_lengths_seconds,
    )
    boussinesq = Boussinesq(grid, regime="steady").recharge_period_series(
        payload=RATES, nper=1, first_clim="mean", label="recharge"
    )

    assert float(recharge_to_spd(model)[0][0]) == pytest.approx(TIME_MEAN)
    assert nwt[0] == pytest.approx(TIME_MEAN)
    assert boussinesq.tolist() == pytest.approx([TIME_MEAN])


def test_criterion_matches_steady_period():
    model = modflow6()

    assert mean_recharge_m_s(model) == pytest.approx(float(recharge_to_spd(model)[0][0]))


MONTH_ENDS = pd.DatetimeIndex(["2000-01-31", "2000-02-29", "2000-03-31"])
MONTH_STARTS = pd.DatetimeIndex(["2000-01-01", "2000-02-01", "2000-03-01"])
MONTH_RATES = np.array([2.0, 8.0, 1.0])
MONTH_TIME_MEAN = float(np.average(MONTH_RATES, weights=[31.0, 29.0, 31.0]))
ONE_PERIOD = (pd.Timestamp("2000-01-01"), pd.Timestamp("2000-04-01"))
ONE_PERIOD_WINDOW = fc.window("2000-01-01", "2000-03-31", period_bounds=(ONE_PERIOD,))

SAMPLE_DAYS = [
    pytest.param(MONTH_ENDS, [31.0, 29.0, 31.0], id="month ends"),
    pytest.param(MONTH_STARTS, [31.0, 29.0, 31.0], id="month starts"),
    pytest.param(pd.DatetimeIndex(["2000-01-15", "2000-02-15"]), [31.0, 29.0], id="mid month"),
    pytest.param(
        pd.DatetimeIndex(["2000-01-01", "2000-02-01", "2000-04-01", "2000-05-01"]),
        [31, 29, 30, 31],
        id="month starts with a gap",
    ),
    pytest.param(pd.DatetimeIndex(["2000-12-31", "2001-12-31"]), [366.0, 365.0], id="year ends"),
    pytest.param(
        pd.DatetimeIndex(["2000-01-01", "2001-01-01", "2003-01-01"]),
        [366.0, 365.0, 365.0],
        id="year starts with a gap",
    ),
]


@pytest.mark.parametrize(("stamps", "expected"), SAMPLE_DAYS)
def test_calendar_sample_days(stamps, expected):
    np.testing.assert_allclose(calendar_sample_days(stamps), expected)


@pytest.mark.parametrize("stamps", [MONTH_ENDS, MONTH_STARTS], ids=["month ends", "month starts"])
def test_one_period_series_time_mean(stamps):
    aligned = align_forcing_series_to_simulation_window(
        pd.Series(MONTH_RATES, index=stamps), simulation_window=ONE_PERIOD_WINDOW
    )

    assert float(aligned.iloc[0]) == pytest.approx(MONTH_TIME_MEAN)


def test_criterion_period_time_mean():
    series = pd.Series(MONTH_RATES, index=MONTH_ENDS)
    end = pd.DatetimeIndex(["2000-04-01"])

    with_start = period_mean_on_index(series, end, start="2000-01-01")
    alone = period_mean_on_index(series, end)

    assert float(with_start.iloc[0]) == pytest.approx(MONTH_TIME_MEAN)
    assert float(alone.iloc[0]) == pytest.approx(MONTH_TIME_MEAN)


def test_nwt_negative_first_clim_to_evt():
    rch, evt = extract_negative_recharge_evt_payload(
        payload={0: 1.0, 1: 2.0},
        nper=2,
        steady=np.array([True, False]),
        first_clim=-0.5,
        durations=[1, 1],
    )

    assert rch == {0: 0.0, 1: 2.0}
    assert evt == {0: 0.5, 1: 0.0}


def test_nwt_no_steady_no_evt():
    payload = {0: 1.0, 1: 2.0}

    rch, evt = extract_negative_recharge_evt_payload(
        payload=payload,
        nper=2,
        steady=np.array([False, False]),
        first_clim=-0.5,
        durations=[1, 1],
    )

    assert rch is payload
    assert evt is None


def negative_first_clim(first_period_steady):
    return Boussinesq(
        first_period_steady=first_period_steady,
        recharge=SimpleNamespace(first_clim=-0.5, values=[1.0, 2.0], heterogeneous_source=None),
        active_sinks_sources=("recharge",),
    )


def test_boussinesq_refuses_deficit():
    with pytest.raises(ValueError, match="no EVT to route a deficit to"):
        negative_first_clim(True).resolve_recharge_series(2)


def test_boussinesq_keeps_rates():
    assert negative_first_clim(False).resolve_recharge_series(2) == (1.0, 2.0)


def test_modflow6_rate_table():
    model = SimpleNamespace(nper=2, ncpl=3, first_clim="mean", steady=[False, False])

    model.recharge = {0: 1.0, 1: 2.0}
    assert recharge_to_spd(model)[1] == pytest.approx([2.0, 2.0, 2.0])

    model.recharge = {0: 1.0}
    with pytest.raises(ValueError, match="gives no rate"):
        recharge_to_spd(model)


def test_nwt_rate_table():
    kwargs = {
        "first_clim": "mean",
        "steady": np.array([False, False]),
        "nper": 2,
        "durations": [1.0, 1.0],
    }

    assert assemble_rch_data(payload={0: 1.0, 1: 2.0}, **kwargs) == {0: 1.0, 1: 2.0}
    with pytest.raises(ValueError, match="gives no rate"):
        assemble_rch_data(payload={0: 1.0}, **kwargs)


def test_nwt_rate_list():
    steady = np.array([True])
    assert assemble_rch_data(
        payload=[1.0, 2.0, 6.0], steady=steady, nper=1, durations=[1.0], first_clim="mean"
    )[0] == pytest.approx(3.0)

    transient = {"steady": np.array([False, False]), "nper": 2, "durations": [1.0, 1.0]}
    assert assemble_rch_data(payload=[1.5], first_clim="mean", **transient) == {0: 1.5, 1: 1.5}
    with pytest.raises(ValueError, match="holds 3 rates and this run has 2 periods"):
        assemble_rch_data(payload=[1.0, 2.0, 6.0], first_clim="mean", **transient)


def test_boussinesq_rate_table():
    kwargs = {"nper": 2, "first_clim": "mean", "label": LABEL}
    solver = Boussinesq(first_period_steady=False)

    series = solver.recharge_period_series(payload={0: 1.0, 1: 2.0}, **kwargs)
    assert series.tolist() == [1.0, 2.0]
    with pytest.raises(ValueError, match="gives no rate"):
        solver.recharge_period_series(payload={0: 1.0}, **kwargs)
