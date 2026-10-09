"""``first_clim`` sets the rate of every steady period, and of no other period.

Before, the same key had three behaviours: MODFLOW 6 replaced the steady
periods of a series and ignored a grid, MODFLOW-NWT and Boussinesq replaced
period 0 whether it was steady or not. And a routed deficit kept the mean
deficit whatever ``first_clim`` said, so the net rate of the steady period was
not the one stated. One rule now, read from
``hydromodpy.physics.forcing.steady_periods``.
"""

from __future__ import annotations

import types

import numpy as np
import pytest

from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig
from hydromodpy.physics.forcing.steady_periods import (
    apply_first_clim,
    split_net_recharge,
    steady_flags,
)
from hydromodpy.solver.boussinesq.forcing.common import ForcingCommonMixin
from hydromodpy.solver.modflow6.builders.recharge import (
    extract_evt_payload,
    extract_evt_payload_2d,
    recharge_to_spd,
)
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter

from ._test_modflow6_boundary_conditions_builders import _build_model
from .modflow_nwt._test_forcing_adapter_builders import _build_solver_mesh

# Net rates of four periods, one of them a deficit.
NET = [2.0, -3.0, 9.0, 1.0]
STEADY_FIRST = [True, False, False, False]


def _net_rate(recharge: dict, deficit: dict, kper: int) -> float:
    return float(np.asarray(recharge[kper]).ravel()[0] - np.asarray(deficit[kper]).ravel()[0])


@pytest.mark.parametrize(
    ("first_clim", "expected"),
    [("mean", np.mean(NET)), ("first", NET[0]), (-1.5, -1.5), (4.0, 4.0)],
)
def test_the_net_rate_of_a_steady_period_is_the_one_first_clim_states(first_clim, expected):
    rates = dict(enumerate(NET))

    recharge, deficit = split_net_recharge(rates, steady=STEADY_FIRST, first_clim=first_clim)

    assert _net_rate(recharge, deficit, 0) == pytest.approx(expected)
    for kper in (1, 2, 3):
        assert _net_rate(recharge, deficit, kper) == pytest.approx(NET[kper])
    assert all(float(np.min(v)) >= 0.0 for v in (*recharge.values(), *deficit.values()))


def test_a_transient_period_keeps_its_own_rate_whatever_its_index():
    rates = {0: np.array([1.0, 2.0]), 1: np.array([3.0, 4.0])}

    out = apply_first_clim(rates, steady=[False, False], first_clim=7.0)

    np.testing.assert_allclose(out[0], [1.0, 2.0])
    np.testing.assert_allclose(out[1], [3.0, 4.0])


def test_every_period_of_a_steady_run_takes_the_rule():
    assert steady_flags(nper=3, flow_regime="steady", first_period_steady=False).all()
    assert steady_flags(nper=3, flow_regime="transient", first_period_steady=True).tolist() == [
        True,
        False,
        False,
    ]
    assert not steady_flags(nper=3, flow_regime="transient", first_period_steady=False).any()


def _mf6_model(*, nper: int, steady: list[bool], first_clim: object):
    model = _build_model()
    model.nper = nper
    model.ncpl = 2
    model.steady = np.asarray(steady, dtype=bool)
    model.first_clim = first_clim
    return model


def test_modflow6_gives_a_grid_per_period_the_first_clim_rate_on_its_steady_period():
    model = _mf6_model(nper=2, steady=[True, False], first_clim="mean")
    model.recharge = {0: np.array([1.0, 3.0]), 1: np.array([3.0, 5.0])}

    spd = recharge_to_spd(model)

    np.testing.assert_allclose(spd[0], [2.0, 4.0])
    np.testing.assert_allclose(spd[1], [3.0, 5.0])


@pytest.mark.parametrize("first_clim", ["mean", "first", -1.5, 4.0])
def test_modflow6_series_and_grids_route_the_same_steady_deficit(first_clim):
    series_model = _mf6_model(nper=4, steady=STEADY_FIRST, first_clim=first_clim)
    series_model.recharge, evt = extract_evt_payload(series_model, np.asarray(NET), True)
    rch = recharge_to_spd(series_model)

    grid_model = _mf6_model(nper=4, steady=STEADY_FIRST, first_clim=first_clim)
    grids = {k: np.full(2, value) for k, value in enumerate(NET)}
    grid_model.recharge, grid_evt = extract_evt_payload_2d(
        grids, True, steady=grid_model.steady, first_clim=first_clim
    )
    grid_rch = recharge_to_spd(grid_model)

    expected = {"mean": np.mean(NET), "first": NET[0]}.get(first_clim, first_clim)
    assert float(rch[0][0]) - float(evt[0]) == pytest.approx(expected)
    assert float(grid_rch[0][0]) - float(grid_evt[0][0]) == pytest.approx(expected)
    for kper in (1, 2, 3):
        assert float(rch[kper][0]) - float(evt[kper]) == pytest.approx(NET[kper])
        assert float(grid_rch[kper][0]) - float(grid_evt[kper][0]) == pytest.approx(NET[kper])


def _nwt_adapter(cfg, *, flow_regime: str, first_period_steady: bool, nper: int):
    flow = types.SimpleNamespace(
        sinks_sources={"recharge": cfg},
        flow_regime=flow_regime,
        active_sinks_sources=["recharge"],
        first_period_steady=first_period_steady,
        config=None,
    )
    return FlowToModflowAdapter(
        flow=flow, domain=None, solver_mesh=_build_solver_mesh(), nper=nper, sink_fill=False
    )


@pytest.mark.parametrize("first_clim", ["mean", "first", -1.5])
def test_modflow_nwt_routes_the_steady_deficit_like_modflow6(first_clim):
    cfg = FlowRechargeConfig(values=NET, first_clim=first_clim, units="m/s", negative_to_evt=True)
    adapter = _nwt_adapter(cfg, flow_regime="transient", first_period_steady=True, nper=4)

    rch = adapter._build_recharge_payload()
    evt, _, _ = adapter._build_etp_payload()

    expected = {"mean": np.mean(NET), "first": NET[0]}.get(first_clim, first_clim)
    assert float(rch[0]) - float(evt[0]) == pytest.approx(expected)
    for kper in (1, 2, 3):
        assert float(rch[kper]) - float(evt[kper]) == pytest.approx(NET[kper])


def test_modflow_nwt_keeps_a_transient_first_period():
    cfg = FlowRechargeConfig(values=[2.0, 4.0, 9.0], first_clim=7.0, units="m/s")
    adapter = _nwt_adapter(cfg, flow_regime="transient", first_period_steady=False, nper=3)

    assert adapter._build_recharge_payload() == {0: 2.0, 1: 4.0, 2: 9.0}


class _BoussinesqForcing(ForcingCommonMixin):
    def __init__(self, flow_regime: str) -> None:
        self.flow = types.SimpleNamespace(flow_regime=flow_regime)
        self.time_grid = None


def test_boussinesq_keeps_period_zero_of_a_transient_run():
    series = _BoussinesqForcing("transient").recharge_period_series(
        payload=[2.0, 4.0, 9.0], nper=3, first_clim="mean", label="recharge"
    )

    np.testing.assert_allclose(series, [2.0, 4.0, 9.0])


def test_boussinesq_steady_run_takes_first_clim():
    series = _BoussinesqForcing("steady").recharge_period_series(
        payload=[2.0, 4.0, 9.0], nper=3, first_clim="first", label="recharge"
    )

    np.testing.assert_allclose(series, [2.0, 2.0, 2.0])


def test_a_negative_steady_rate_needs_the_evt_routing():
    with pytest.raises(ValueError, match="negative_to_evt is false"):
        FlowRechargeConfig(values=[1.0, 2.0], first_clim=-1.0, negative_to_evt=False)
    FlowRechargeConfig(values=[1.0, 2.0], first_clim=-1.0, negative_to_evt=True)
