"""``first_clim`` sets the recharge rate (m/s) of every steady period, and of no other period.

The rule lives in ``hydromodpy.model.forcing.steady_periods`` and is shared by
MODFLOW 6, MODFLOW-NWT and Boussinesq. A negative net rate is a deficit routed
to evapotranspiration, so recharge minus deficit is the rate that was stated.
The tests use a four-period record, in rate units where only the ratios matter.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.model.forcing.steady_periods import apply_first_clim, split_net_recharge
from hydromodpy.model.model import ModelTime
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.solver.boussinesq.forcing.common import ForcingCommonMixin
from hydromodpy.solver.modflow6.builders.recharge import (
    bind_recharge_from_flow,
    extract_evt_payload_2d,
    finalize_pending_recharge_evt,
    recharge_to_spd,
)
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter
from hydromodpy.solver.modflow_nwt.nwt.payloads import recharge_etp
from tests._helpers.mf6_toy_models import toy_model
from tests._helpers.model_factory import make_model

from .modflow_nwt._test_forcing_adapter_builders import _build_solver_mesh

# Net rates of four periods, one of them a deficit, and an all-positive record.
NET = [2.0, -3.0, 9.0, 1.0]
POSITIVE = [2.0, 4.0, 9.0, 1.0]
STEADY_FIRST = [True, False, False, False]
FIRST_CLIM = ["mean", "first", -1.5, 4.0]


def expected_rate(first_clim, record):
    """The rate a steady period takes: the mean or first value of the record, or the number."""
    return {"mean": np.mean(record), "first": record[0]}.get(first_clim, first_clim)


def net_rate(recharge, deficit, kper):
    return float(np.asarray(recharge[kper]).ravel()[0] - np.asarray(deficit[kper]).ravel()[0])


def mf6_model(*, nper, steady, first_clim):
    model = toy_model()
    model.nper = nper
    model.perlen = np.ones(nper)
    model.ncpl = 2
    model.steady = np.asarray(steady, dtype=bool)
    model.first_clim = first_clim
    return model


def bind_mf6_series(values, *, first_clim, steady, deferred):
    """Bind a recharge series the way the build does, with the model's first_clim left unset."""
    model = mf6_model(nper=len(steady), steady=steady, first_clim=None)
    cfg = FlowRechargeConfig(
        values=list(values), first_clim=first_clim, units="m/s", negative_to_evt=True
    )
    model.inputs = make_model(active_sinks_sources=("recharge",), recharge=cfg)
    if deferred:
        del model.nper
        bind_recharge_from_flow(model)
        model.nper = len(steady)
        finalize_pending_recharge_evt(model)
    else:
        bind_recharge_from_flow(model)
    return recharge_to_spd(model), model._evt_rate_payload


def evt_rate(evt, kper):
    return 0.0 if evt is None else float(np.asarray(evt[kper]).ravel()[0])


def mf6_grids(record, first_clim):
    """Recharge and deficit per period of a record given as one grid per period."""
    model = mf6_model(nper=4, steady=STEADY_FIRST, first_clim=first_clim)
    grids = {k: np.full(2, value) for k, value in enumerate(record)}
    model.recharge, evt = extract_evt_payload_2d(
        grids, True, steady=model.steady, first_clim=first_clim, durations=model.perlen
    )
    return recharge_to_spd(model), evt


def nwt_adapter(cfg, *, regime, first_period_steady, nper):
    model = make_model(
        recharge=cfg,
        active_sinks_sources=("recharge",),
        time=ModelTime(grid=None, regime=regime, first_period_steady=first_period_steady),
    )
    return FlowToModflowAdapter(
        model=model, solver_mesh=_build_solver_mesh(), nper=nper, sink_fill=False
    )


class BoussinesqForcing(ForcingCommonMixin):
    def __init__(self, regime, first_period_steady):
        self.inputs = make_model(
            time=ModelTime(grid=None, regime=regime, first_period_steady=first_period_steady)
        )


# Per-cell rates (m/s) of three periods, two cells.
MAPPING = {
    0: np.array([2.0e-6, -1.0e-6]),
    1: np.array([4.0e-6, 4.0e-6]),
    2: np.array([-3.0e-6, -2.0e-6]),
}

SPLITS = [
    # A steady period carries the per-cell time mean of the positives and of the deficits.
    pytest.param(
        MAPPING, [True, False, False], 0, [2.0e-6, 4.0e-6 / 3], [1.0e-6, 1.0e-6], id="steady"
    ),
    pytest.param(MAPPING, [True, False, False], 2, [0.0, 0.0], [3.0e-6, 2.0e-6], id="transient"),
    # Keyed on the steady flag, not on period 0.
    pytest.param(MAPPING, [False] * 3, 0, [2.0e-6, 0.0], [0.0, 1.0e-6], id="no steady period"),
    # 1.0e-7 m/s is 8.64 mm/day, -1.0e-6 m/s is -86.4 mm/day
    pytest.param(
        {0: np.array([1.0e-7]), 1: np.array([-1.0e-6])},
        [True, False],
        0,
        [0.5e-7],
        [0.5e-6],
        id="two periods, one deficit",
    ),
]


@pytest.mark.parametrize(("mapping", "steady", "kper", "clipped", "deficit"), SPLITS)
def test_split_of_net_recharge(mapping, steady, kper, clipped, deficit):
    out_clipped, out_evt = split_net_recharge(
        mapping, steady=steady, first_clim="mean", durations=np.ones(len(steady))
    )
    np.testing.assert_allclose(out_clipped[kper], clipped)
    np.testing.assert_allclose(out_evt[kper], deficit)


@pytest.mark.parametrize(
    "first_clim",
    [
        pytest.param("mean", id="mean"),
        pytest.param("first", id="first"),
        pytest.param(-1.5, id="negative number"),
        pytest.param(4.0, id="positive number"),
    ],
)
def test_net_rate_of_steady_period(first_clim):
    recharge, deficit = split_net_recharge(
        dict(enumerate(NET)), steady=STEADY_FIRST, first_clim=first_clim, durations=np.ones(4)
    )

    assert net_rate(recharge, deficit, 0) == pytest.approx(expected_rate(first_clim, NET))
    for kper in (1, 2, 3):
        assert net_rate(recharge, deficit, kper) == pytest.approx(NET[kper])
    assert all(float(np.min(v)) >= 0.0 for v in (*recharge.values(), *deficit.values()))


def test_transient_period_keeps_its_rate():
    rates = {0: np.array([1.0, 2.0]), 1: np.array([3.0, 4.0])}

    out = apply_first_clim(rates, steady=[False, False], first_clim=7.0, durations=[1.0, 1.0])

    np.testing.assert_allclose(out[0], [1.0, 2.0])
    np.testing.assert_allclose(out[1], [3.0, 4.0])


def test_mf6_steady_period_grid():
    model = mf6_model(nper=2, steady=[True, False], first_clim="mean")
    model.recharge = {0: np.array([1.0, 3.0]), 1: np.array([3.0, 5.0])}

    spd = recharge_to_spd(model)

    np.testing.assert_allclose(spd[0], [2.0, 4.0])
    np.testing.assert_allclose(spd[1], [3.0, 5.0])


def test_mf6_steady_period_series():
    model = mf6_model(nper=3, steady=[True, False, False], first_clim="mean")
    model.recharge = np.array([1.0e-7, 2.0e-7, 3.0e-7])
    spd = recharge_to_spd(model)
    np.testing.assert_allclose(spd[0], [2.0e-7, 2.0e-7])  # mean over the 3 periods
    np.testing.assert_allclose(spd[1], [2.0e-7, 2.0e-7])
    np.testing.assert_allclose(spd[2], [3.0e-7, 3.0e-7])

    model.first_clim = "first"
    assert recharge_to_spd(model)[0][0] == pytest.approx(1.0e-7)

    model.recharge = np.array([5.0e-8, 2.0e-7, 3.0e-7])
    model.first_clim = 5.0e-8
    assert recharge_to_spd(model)[0][0] == pytest.approx(5.0e-8)


@pytest.mark.parametrize("deferred", [False, True], ids=["bound at once", "bound before nper"])
@pytest.mark.parametrize("first_clim", FIRST_CLIM)
def test_mf6_series_and_grids_agree(first_clim, deferred):
    rch, evt = bind_mf6_series(NET, first_clim=first_clim, steady=STEADY_FIRST, deferred=deferred)
    grid_rch, grid_evt = mf6_grids(NET, first_clim)

    assert float(rch[0][0]) - evt_rate(evt, 0) == pytest.approx(expected_rate(first_clim, NET))
    assert float(grid_rch[0][0]) - float(grid_evt[0][0]) == pytest.approx(
        expected_rate(first_clim, NET)
    )
    for kper in (1, 2, 3):
        assert float(rch[kper][0]) - evt_rate(evt, kper) == pytest.approx(NET[kper])
        assert float(grid_rch[kper][0]) - float(grid_evt[kper][0]) == pytest.approx(NET[kper])


@pytest.mark.parametrize("deferred", [False, True], ids=["bound at once", "bound before nper"])
def test_mf6_negative_first_clim_in_series(deferred):
    rch, evt = bind_mf6_series(POSITIVE, first_clim=-3.0, steady=STEADY_FIRST, deferred=deferred)

    assert float(rch[0][0]) - evt_rate(evt, 0) == pytest.approx(-3.0)
    for kper in (1, 2, 3):
        assert float(rch[kper][0]) - evt_rate(evt, kper) == pytest.approx(POSITIVE[kper])


def test_mf6_negative_first_clim_in_grids():
    rch, evt = mf6_grids(POSITIVE, -3.0)

    assert evt is not None
    np.testing.assert_allclose(rch[0] - evt[0], -3.0)
    for kper in (1, 2, 3):
        np.testing.assert_allclose(rch[kper] - evt[kper], POSITIVE[kper])


def test_mf6_no_deficit_without_steady_period():
    _, evt = bind_mf6_series(POSITIVE, first_clim=-3.0, steady=[False] * 4, deferred=True)

    assert evt is None


@pytest.mark.parametrize(
    "first_clim", [pytest.param("mean", id="mean"), pytest.param("first", id="first"), 7.0]
)
def test_mf6_one_steady_period(first_clim):
    # With one period the rule reads the whole record.
    model = mf6_model(nper=1, steady=[True], first_clim=first_clim)
    model.recharge = np.asarray(POSITIVE)
    spd = recharge_to_spd(model)
    assert float(spd[0][0]) == pytest.approx(expected_rate(first_clim, POSITIVE))

    rch, evt = bind_mf6_series(NET, first_clim=first_clim, steady=[True], deferred=True)
    assert float(rch[0][0]) - evt_rate(evt, 0) == pytest.approx(expected_rate(first_clim, NET))


@pytest.mark.parametrize(
    "first_clim", [pytest.param("mean", id="mean"), pytest.param("first", id="first"), -1.5]
)
def test_nwt_routes_steady_deficit(first_clim):
    cfg = FlowRechargeConfig(values=NET, first_clim=first_clim, units="m/s", negative_to_evt=True)
    adapter = nwt_adapter(cfg, regime="transient", first_period_steady=True, nper=4)

    rch = adapter._build_recharge_payload()
    evt, _, _ = adapter._build_etp_payload()

    assert float(rch[0]) - float(evt[0]) == pytest.approx(expected_rate(first_clim, NET))
    for kper in (1, 2, 3):
        assert float(rch[kper]) - float(evt[kper]) == pytest.approx(NET[kper])


# regime, first_period_steady, record, nper, first_clim, series
BOUSSINESQ_SERIES = [
    pytest.param(
        "transient",
        False,
        [2.0, 4.0, 9.0],
        3,
        "mean",
        [2.0, 4.0, 9.0],
        id="transient keeps period 0",
    ),
    pytest.param(
        "transient", True, [2.0, 4.0, 9.0], 3, "mean", [5.0, 4.0, 9.0], id="steady first, mean"
    ),
    pytest.param(
        "transient", True, [2.0, 4.0, 9.0], 3, "first", [2.0, 4.0, 9.0], id="steady first, first"
    ),
    pytest.param(
        "transient", True, [2.0, 4.0, 9.0], 3, 7.0, [7.0, 4.0, 9.0], id="steady first, number"
    ),
    pytest.param("steady", False, [2.0, 4.0, 9.0], 3, "first", [2.0, 2.0, 2.0], id="steady run"),
    # A steady run resolves its forcing with nper = 1, and "first" is still R_0.
    pytest.param(
        "steady", False, [2.0, 4.0, 9.0, 1.0], 1, "mean", [4.0], id="one steady period, mean"
    ),
    pytest.param(
        "steady", False, [2.0, 4.0, 9.0, 1.0], 1, "first", [2.0], id="one steady period, first"
    ),
    pytest.param(
        "steady", False, [2.0, 4.0, 9.0, 1.0], 1, 7.0, [7.0], id="one steady period, number"
    ),
    pytest.param(
        "transient", False, [2.0, 4.0, 9.0, 1.0], 1, "first", [4.0], id="one transient period"
    ),
]


@pytest.mark.parametrize(
    ("regime", "first_period_steady", "record", "nper", "first_clim", "series"), BOUSSINESQ_SERIES
)
def test_boussinesq_period_series(regime, first_period_steady, record, nper, first_clim, series):
    out = BoussinesqForcing(regime, first_period_steady).recharge_period_series(
        payload=record, nper=nper, first_clim=first_clim, label="recharge"
    )

    np.testing.assert_allclose(out, series)


def test_negative_steady_rate_needs_evt_routing():
    with pytest.raises(ValueError, match="negative_to_evt is false"):
        FlowRechargeConfig(values=[1.0, 2.0], first_clim=-1.0, negative_to_evt=False)
    FlowRechargeConfig(values=[1.0, 2.0], first_clim=-1.0, negative_to_evt=True)


def test_mf6_and_nwt_share_the_split():
    assert recharge_etp.split_net_recharge is split_net_recharge
