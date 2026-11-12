"""Native-step series of a forcing: values (m/s) at the steps the source was written on."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.model.forcing.native import NativeSeries, native_series

pytestmark = pytest.mark.fast

MM_DAY_TO_M_S = 1.0e-3 / 86_400.0


def _Source(points: list[Any] | None = None, fields: list[Any] | None = None) -> SimpleNamespace:
    # A LoadResult as the binders read it.
    points, fields = points or [], fields or []
    return SimpleNamespace(
        points=points, fields=fields, has_points=bool(points), has_fields=bool(fields)
    )


def _point_series(values: Any, index: Any) -> Any:
    frame = pd.DataFrame({"datetime": pd.DatetimeIndex(index), "value": values})
    return type("Rec", (), {"variable": "recharge", "data": frame})()


def _window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2026-01-01"),
        end=pd.Timestamp("2026-01-05"),
        step_value=1,
        step_unit="day",
        coverage_policy="error",
    )


def test_point_source_own_step() -> None:
    index = pd.date_range("2026-01-01", periods=3, freq="D")
    values = np.array([10.0, 20.0, 30.0])
    native = native_series(
        _Source(points=[_point_series(values, index)]), _window(), factor=MM_DAY_TO_M_S
    )
    assert native is not None
    assert len(native) == 3
    np.testing.assert_allclose(native.values, values * MM_DAY_TO_M_S)
    # One more edge than values: the last step closes at the end of the run,
    # the day after its inclusive end.
    pd.testing.assert_index_equal(native.starts, pd.DatetimeIndex([*index, "2026-01-06"]))


def test_stations_mean_per_step() -> None:
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    native = native_series(
        _Source(
            points=[
                _point_series([10.0, 20.0], index),
                _point_series([30.0, 40.0], index),
            ]
        ),
        _window(),
        factor=MM_DAY_TO_M_S,
    )
    assert native is not None
    np.testing.assert_allclose(native.values, np.array([20.0, 30.0]) * MM_DAY_TO_M_S)


def test_field_area_mean_per_step() -> None:
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    values = np.zeros((2, 4, 4))
    values[:, :2, :] = 10.0
    values[:, 2:, :] = 30.0
    dataset = _field_dataset(values=values, index=index)
    native = native_series(
        _Source(fields=[dataset]),
        _window(),
        factor=MM_DAY_TO_M_S,
        cell_polygon=Polygon([(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)]),
    )
    assert native is not None
    np.testing.assert_allclose(native.values, np.array([20.0, 20.0]) * MM_DAY_TO_M_S)


def test_series_written_per_period() -> None:
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    values = np.array([1.0, 2.0, 3.0, 4.0])
    native = native_series(_Source(points=[_point_series(values, index)]), _window())
    assert native is not None
    np.testing.assert_allclose(native.values, values)


def test_series_cut_to_window() -> None:
    index = pd.DatetimeIndex(["2025-12-30", "2025-12-31", "2026-01-01", "2026-01-02", "2026-01-05"])
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    native = native_series(_Source(points=[_point_series(values, index)]), _window())
    assert native is not None
    # A step starts on the first instant of the run, so no step before it is
    # read; the step that starts on the end of the window holds nothing of it.
    pd.testing.assert_index_equal(
        native.starts, pd.DatetimeIndex(["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"])
    )
    np.testing.assert_allclose(native.values, [3.0, 4.0, 5.0])


def test_first_step_starts_with_run() -> None:
    index = pd.DatetimeIndex(["2025-12-30", "2025-12-31", "2026-01-03"])
    native = native_series(_Source(points=[_point_series([1.0, 2.0, 3.0], index)]), _window())
    assert native is not None
    pd.testing.assert_index_equal(
        native.starts, pd.DatetimeIndex(["2026-01-01", "2026-01-03", "2026-01-06"])
    )
    np.testing.assert_allclose(native.values, [2.0, 3.0])


def test_factor_converts_to_m_s() -> None:
    index = pd.date_range("2026-01-01", periods=1, freq="D")
    native = native_series(
        _Source(points=[_point_series([10.0], index)]), _window(), factor=MM_DAY_TO_M_S
    )
    assert native is not None
    np.testing.assert_allclose(native.values, 10.0 * MM_DAY_TO_M_S)


DAYS_3 = pd.date_range("2026-01-01", periods=3, freq="D")
DAYS_2 = pd.date_range("2026-01-01", periods=2, freq="D")

REFUSALS = [
    pytest.param(DAYS_3, [1.0], "one value per step", id="fewer values than steps"),
    pytest.param(DAYS_2, [1.0, 2.0], "one value per step", id="as many values as edges"),
    pytest.param(
        pd.DatetimeIndex(["2026-01-02", "2026-01-01"]),
        [1.0],
        "unique and increasing",
        id="reversed",
    ),
    pytest.param(
        pd.DatetimeIndex(["2026-01-01", "2026-01-01"]),
        [1.0],
        "unique and increasing",
        id="repeated",
    ),
]


@pytest.mark.parametrize(("starts", "values", "match"), REFUSALS)
def test_refusals(starts, values, match) -> None:
    with pytest.raises(ValueError, match=match):
        NativeSeries(starts=starts, values=values)


def _field_dataset(values: Any, index: Any) -> Any:
    # A stand-in field record: 4 x 4 pixels of 10 m over the square cell,
    # values laid out (time, y, x) with y descending.
    import xarray as xr

    data = xr.Dataset(
        {"recharge": (("time", "y", "x"), np.asarray(values, dtype=float))},
        coords={
            "x": [5.0, 15.0, 25.0, 35.0],
            "y": [35.0, 25.0, 15.0, 5.0],
            "time": pd.DatetimeIndex(index),
        },
    )
    return type("Rec", (), {"variable": "recharge", "data": data})()


def test_native_aligns_to_model_recharge() -> None:
    # The binder builds both views from one point source. Recharge varies inside
    # each period of three days, so the period values are compared to the bit.
    from hydromodpy.model.boundaries.climate import apply_recharge_load_result_to_flow
    from hydromodpy.model.flow import Flow
    from hydromodpy.model.flow_config import FlowConfig
    from hydromodpy.model.forcing.time_alignment import align_forcing_series_to_simulation_window

    index = pd.date_range("2026-01-01", periods=12, freq="D")
    values = np.random.default_rng(3).uniform(0.0, 8.0, index.size)
    window = ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2026-01-01"),
        end=pd.Timestamp("2026-01-12"),
        step_value=3,
        step_unit="day",
        coverage_policy="error",
    )
    flow = Flow(FlowConfig.model_validate({"sinks_sources": {"recharge": {}}}))

    bound = apply_recharge_load_result_to_flow(
        flow=flow,
        recharge_result=_Source(points=[_point_series(values, index)]),
        simulation_window=window,
    )

    assert bound
    native = flow.native_recharge
    assert native is not None and len(native) == index.size
    aligned = align_forcing_series_to_simulation_window(
        pd.Series(native.values, index=native.starts[:-1]),
        simulation_window=window,
        label="recharge",
    )
    period_view = np.asarray(flow.sinks_sources["recharge"].values, dtype=float)
    assert period_view.size == 4
    assert np.array_equal(aligned.to_numpy(dtype=float), period_view)
