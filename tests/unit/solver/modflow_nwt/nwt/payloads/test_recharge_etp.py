"""Recharge and evapotranspiration payloads of the NWT adapter.

Rates are in m/s, a payload holds one rate (or one array of cells) per stress period.
A negative recharge is a loss, so it goes to the EVT package and RCH keeps the positive part.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.model.model import ModelTime
from hydromodpy.model.sinks_sources.etp import FlowEtpConfig
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter
from hydromodpy.solver.modflow_nwt.nwt.payloads.recharge_etp import (
    apply_first_clim_2d,
    assemble_rch_data,
    build_etp_payload,
    build_heterogeneous_etp_payload,
    build_recharge_payload,
    clip_etp_to_non_negative,
    clip_negative_payload,
    copy_payload,
    extract_negative_recharge_evt_payload,
    merge_evt_payloads,
)
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

MM_DAY = 1.0e-3 / 86400.0  # 1 mm/day in m/s


def grid_mesh(nrow=1, ncol=1):
    """Cells of 1 m under a flat top at 0 m."""
    return solver_mesh_from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=np.zeros((nrow, ncol)),
        botm=np.full((1, nrow, ncol), -10.0),
        dx=1.0,
        dy=1.0,
    )


def sinks_adapter(
    nper, mesh=None, window=None, steady_first=False, **members
) -> FlowToModflowAdapter:
    model = make_model(
        time=ModelTime(grid=None, regime="transient", first_period_steady=steady_first),
        **members,
    )
    return FlowToModflowAdapter(
        model=model,
        solver_mesh=grid_mesh() if mesh is None else mesh,
        nper=nper,
        sink_fill=False,
        simulation_window=window,
    )


def february_window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2003-01-01"),
        end=pd.Timestamp("2003-02-28"),
        step_value=1,
        step_unit="month",
        coverage_policy="error",
    )


def point_source(variable: str, january_mm_day: float, february_mm_day: float) -> LoadResult:
    dates = pd.date_range("2003-01-01", "2003-02-28", freq="D")
    values = np.where(dates.month == 2, february_mm_day, january_mm_day).astype(float)
    record = PointRecord(
        station_id="S1",
        variable=variable,
        source="test",
        unit="mm/day",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": values}),
        date_start=datetime(2003, 1, 1),
        date_end=datetime(2003, 2, 28),
        location=StationLocation(id="S1", x=0.5, y=0.5, crs="EPSG:2154"),
    )
    return LoadResult(points=[record])


# Clipping a payload at zero keeps its container.


class Uncopyable:
    def copy(self):
        raise RuntimeError("no copy")


def test_unreadable_copy_keeps_payload():
    payload = Uncopyable()

    assert copy_payload(payload) is payload


CLIPS_ETP = [
    pytest.param({0: -1.0, 1: 2.0}, {0: 0.0, 1: 2.0}, id="mapping"),
    pytest.param(pd.Series([-1.0, 2.0]), [0.0, 2.0], id="series"),
    pytest.param([-1.0, 2.0], [0.0, 2.0], id="list"),
    pytest.param(np.array([-1.0, 2.0]), [0.0, 2.0], id="array"),
    pytest.param(-3.0, 0.0, id="scalar"),
]


@pytest.mark.parametrize(("payload", "expected"), CLIPS_ETP)
def test_clip_etp(payload, expected):
    clipped = clip_etp_to_non_negative(payload)

    if isinstance(expected, dict):
        assert clipped == expected
    else:
        np.testing.assert_allclose(clipped, expected)


CLIPS_RECHARGE = [
    pytest.param({0: -1.0, 1: [-2.0, 3.0]}, {0: 0.0, 1: [0.0, 3.0]}, id="mapping"),
    pytest.param(-1.0, 0.0, id="scalar"),
    pytest.param(pd.Series([-1.0, 2.0]), [0.0, 2.0], id="series"),
    pytest.param(np.array([-1.0, 2.0]), [0.0, 2.0], id="array"),
    pytest.param([-1.0, 2.0], [0.0, 2.0], id="list"),
]


@pytest.mark.parametrize(("payload", "expected"), CLIPS_RECHARGE)
def test_clip_negative_recharge(payload, expected):
    clipped = clip_negative_payload(payload)

    if isinstance(expected, dict):
        assert set(clipped) == set(expected)
        for key, value in expected.items():
            np.testing.assert_allclose(clipped[key], value)
    else:
        np.testing.assert_allclose(clipped, expected)


# Negative recharge on a transient run, given as an array.


def test_negative_array_goes_to_evt():
    rch, evt = extract_negative_recharge_evt_payload(
        payload=np.array([0.1, -0.2, 0.3]),
        nper=3,
        steady=np.zeros(3, dtype=bool),
        first_clim="first",
        durations=np.ones(3),
    )

    assert rch == {0: pytest.approx(0.1), 1: 0.0, 2: pytest.approx(0.3)}
    assert evt == {0: 0.0, 1: pytest.approx(0.2), 2: 0.0}


def test_evt_payloads_add():
    primary = {0: 1.0, 1: 2.0}
    extra = {0: 0.5}

    merged = merge_evt_payloads(primary, extra, nper=2)

    np.testing.assert_allclose([merged[0], merged[1]], [1.5, 2.0])  # a missing period adds 0
    assert merge_evt_payloads(None, extra, nper=2) is extra


def test_negative_rates_allowed():
    rates = assemble_rch_data(
        payload=[0.1, -0.2],
        first_clim="mean",
        steady=np.zeros(2, dtype=bool),
        nper=2,
        durations=np.ones(2),
        allow_negative=True,
    )

    assert rates == {0: pytest.approx(0.1), 1: pytest.approx(-0.2)}


def test_negative_arrays_allowed():
    raw = {0: np.full((1, 2), -1.0), 1: np.full((1, 2), 2.0)}

    arrays = apply_first_clim_2d(
        raw_arrays=raw,
        first_clim="mean",
        steady=np.zeros(2, dtype=bool),
        durations=np.ones(2),
        allow_negative=True,
    )

    np.testing.assert_allclose(arrays[0], [[-1.0, -1.0]])
    np.testing.assert_allclose(arrays[1], [[2.0, 2.0]])


# Gridded and station sources on the grid.


def field_source(rates_m_s) -> LoadResult:
    """One static field of 2 x 2 pixels of 1 m, north row first."""
    dataset = xr.Dataset(
        {"recharge": (("y", "x"), np.asarray(rates_m_s))},
        coords={"x": [0.5, 1.5], "y": [1.5, 0.5]},
    )
    record = FieldRecord(
        variable="recharge",
        source="test",
        unit="m/s",
        data=dataset,
        bbox=(0.0, 0.0, 2.0, 2.0),
        crs="EPSG:2154",
    )
    return LoadResult(fields=[record])


def test_field_source_on_cells():
    rates = [[1.0e-7, 2.0e-7], [3.0e-7, 4.0e-7]]
    config = FlowRechargeConfig(
        values=0.0,
        first_clim="first",
        heterogeneous_source=field_source(rates),
        interpolation_method="nearest",
    )
    adapter = sinks_adapter(
        1,
        mesh=grid_mesh(nrow=2, ncol=2),
        recharge=config,
        active_sinks_sources=("recharge",),
    )

    rch = build_recharge_payload(adapter)

    # Each 1 m cell reads the pixel under its center.
    np.testing.assert_allclose(rch[0], rates)


def test_negative_station_recharge_goes_to_evt():
    config = FlowRechargeConfig(
        values=0.0,
        first_clim="first",
        heterogeneous_source=point_source("recharge", -8.0, 4.0),
        interpolation_method="nearest",
        negative_to_evt=True,
    )
    adapter = sinks_adapter(
        2, window=february_window(), recharge=config, active_sinks_sources=("recharge",)
    )

    rch = build_recharge_payload(adapter)
    evt, _, _ = build_etp_payload(adapter)

    # January loses 8 mm/day, which EVT takes. February gains 4 mm/day.
    np.testing.assert_allclose([rch[0], rch[1]], [[[0.0]], [[4 * MM_DAY]]])
    np.testing.assert_allclose([evt[0], evt[1]], [[[8 * MM_DAY]], [[0.0]]])


def test_station_etp_on_cells():
    config = FlowEtpConfig(
        values=0.0,
        units="m/s",
        first_clim="first",
        extinction_depth=3.0,
        heterogeneous_source=point_source("etp", 6.0, 2.0),
        interpolation_method="nearest",
    )
    adapter = sinks_adapter(2, window=february_window(), etp=config, active_sinks_sources=("etp",))

    evt, _, extinction = build_etp_payload(adapter)

    np.testing.assert_allclose([evt[0], evt[1]], [[[6 * MM_DAY]], [[2 * MM_DAY]]])
    assert extinction == 3.0


def test_empty_source_gives_zero_etp():
    config = FlowEtpConfig(values=0.0, units="m/s", heterogeneous_source=LoadResult())
    adapter = sinks_adapter(2, etp=config, active_sinks_sources=("etp",))

    evt = build_heterogeneous_etp_payload(adapter, config)

    np.testing.assert_allclose([evt[0], evt[1]], [[[0.0]], [[0.0]]])


def test_etp_without_config():
    adapter = sinks_adapter(1, etp=None, active_sinks_sources=("etp",))

    assert build_etp_payload(adapter) == (None, 2.0, 1.0)  # no EVT, default offset and depth m


def test_empty_recharge_mapping_refused():
    with pytest.raises(ValueError, match="mapping cannot be empty"):
        assemble_rch_data(
            payload={}, first_clim="mean", steady=np.zeros(1, dtype=bool), nper=1, durations=None
        )
