from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig
from hydromodpy.solver.modflow6.builders import (
    bind_recharge_from_flow,
    recharge_to_spd,
    resolve_deferred_heterogeneous_recharge,
)

from ._test_modflow6_boundary_conditions_builders import (
    _build_model,
    _build_unstructured_model,
)


def _make_recharge_point_record(
    *,
    station_id: str,
    x: float,
    y: float,
    january_value_mm_day: float,
    february_value_mm_day: float | None = None,
) -> PointRecord:
    dates = pd.date_range("2003-01-01", "2003-02-28", freq="D")
    values = np.full(len(dates), float(january_value_mm_day), dtype=float)
    if february_value_mm_day is not None:
        values[dates.month == 2] = float(february_value_mm_day)
    return PointRecord(
        station_id=station_id,
        variable="recharge",
        source="test",
        unit="mm/day",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": values}),
        date_start=datetime(2003, 1, 1),
        date_end=datetime(2003, 2, 28),
        location=StationLocation(id=station_id, x=x, y=y, crs="EPSG:2154"),
    )


def test_modflow6_binds_recharge_from_flow_sinks_sources() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        sinks_sources={
            "recharge": FlowRechargeConfig(
                values=pd.Series([0.5, 0.3], dtype=float),
                first_clim="first",
                units="mm/day",
            )
        },
        active_sinks_sources=["recharge"],
    )

    bind_recharge_from_flow(model)
    spd = recharge_to_spd(model)

    # DISV: recharge arrays are flat (ncpl,)
    assert spd[0].shape == (6,)
    assert np.allclose(spd[0], 0.5e-3 / 86400.0)
    assert np.allclose(spd[1], 0.3e-3 / 86400.0)


def test_modflow6_rejects_nonfinite_direct_recharge() -> None:
    model = _build_model()
    model.recharge = np.asarray([1.0e-8, np.nan], dtype=float)

    with pytest.raises(ValueError, match="model.recharge"):
        bind_recharge_from_flow(model)


def test_modflow6_rejects_bad_recharge_flat_shape() -> None:
    model = _build_model()
    model.recharge = np.asarray([1.0e-8, 2.0e-8, 3.0e-8], dtype=float)

    with pytest.raises(ValueError, match="sequence length"):
        recharge_to_spd(model)


def test_modflow6_single_period_recharge_sequence_uses_first_clim() -> None:
    model = _build_model()
    model.nper = 1
    model.first_clim = "mean"
    model.recharge = np.asarray([1.0e-8, 2.0e-8, 3.0e-8], dtype=float)

    spd = recharge_to_spd(model)

    assert np.allclose(spd[0], 2.0e-8)


def test_modflow6_rejects_missing_recharge_mapping_period() -> None:
    model = _build_model()
    model.recharge = {0: np.full(6, 1.0e-8, dtype=float)}

    with pytest.raises(ValueError, match="missing stress period 1"):
        recharge_to_spd(model)


def test_modflow6_resolves_point_recharge_on_unstructured_runtime_mesh() -> None:
    model = _build_unstructured_model()
    point = _make_recharge_point_record(
        station_id="R1",
        x=0.75,
        y=0.25,
        january_value_mm_day=8.0,
    )
    model.flow = SimpleNamespace(
        sinks_sources={
            "recharge": FlowRechargeConfig(
                values=0.0,
                heterogeneous_source=LoadResult(points=[point]),
                interpolation_method="nearest",
            )
        },
        active_sinks_sources=["recharge"],
    )

    bind_recharge_from_flow(model)
    resolve_deferred_heterogeneous_recharge(model)

    expected = 8.0e-3 / 86400.0
    np.testing.assert_allclose(
        model.recharge[0],
        np.full(2, expected, dtype=float),
    )
    np.testing.assert_allclose(
        model.recharge[1],
        np.full(2, expected, dtype=float),
    )


def test_modflow6_defaults_to_zero_recharge_when_inactive() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        sinks_sources={},
        active_sinks_sources=[],
    )

    bind_recharge_from_flow(model)
    spd = recharge_to_spd(model)

    assert spd[0].shape == (6,)
    assert np.allclose(spd[0], 0.0)
    assert np.allclose(spd[1], 0.0)
