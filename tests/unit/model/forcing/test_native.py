"""The native-step series of a forcing, unit tests of ``model/forcing/native``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.model.forcing.native import NativeSeries, native_series

pytestmark = pytest.mark.fast

MM_DAY_TO_M_S = 1.0e-3 / 86_400.0


@dataclass
class _Source:
    """A ``LoadResult`` as the binders read it, with the records a test fills."""

    points: list[Any] = field(default_factory=list)
    fields: list[Any] = field(default_factory=list)

    @property
    def has_points(self) -> bool:
        return bool(self.points)

    @property
    def has_fields(self) -> bool:
        return bool(self.fields)


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


def test_a_point_source_gives_its_series_at_its_own_step() -> None:
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


def test_several_stations_mean_at_each_of_their_steps() -> None:
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


def test_a_spatial_source_outside_a_lumped_mesh_gives_no_native_series() -> None:
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    dataset = _field_dataset(values=np.full((2, 4, 4), 5.0), index=index)
    native = native_series(_Source(fields=[dataset]), _window())
    assert native is None


def test_a_spatial_source_on_the_cell_gives_the_area_mean_at_each_step() -> None:
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


def test_a_series_written_for_the_periods_gives_its_period_values() -> None:
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    values = np.array([1.0, 2.0, 3.0, 4.0])
    native = native_series(_Source(points=[_point_series(values, index)]), _window())
    assert native is not None
    np.testing.assert_allclose(native.values, values)


def test_the_series_is_cut_to_the_window_of_the_run() -> None:
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


def test_a_step_that_covers_the_start_of_the_run_begins_there() -> None:
    """The step before the run holds over its first instant from the start only."""
    index = pd.DatetimeIndex(["2025-12-30", "2025-12-31", "2026-01-03"])
    native = native_series(_Source(points=[_point_series([1.0, 2.0, 3.0], index)]), _window())
    assert native is not None
    pd.testing.assert_index_equal(
        native.starts, pd.DatetimeIndex(["2026-01-01", "2026-01-03", "2026-01-06"])
    )
    np.testing.assert_allclose(native.values, [2.0, 3.0])


def test_without_a_window_the_last_step_closes_one_step_of_the_source_later() -> None:
    index = pd.date_range("2026-01-01", periods=3, freq="2D")
    native = native_series(_Source(points=[_point_series([1.0, 2.0, 3.0], index)]), None)
    assert native is not None
    assert native.starts[-1] == pd.Timestamp("2026-01-07")
    single = native_series(_Source(points=[_point_series([1.0], index[:1])]), None)
    assert single is None


def test_the_factor_carries_the_source_unit_to_m_per_s() -> None:
    index = pd.date_range("2026-01-01", periods=1, freq="D")
    native = native_series(
        _Source(points=[_point_series([10.0], index)]), _window(), factor=MM_DAY_TO_M_S
    )
    assert native is not None
    np.testing.assert_allclose(native.values, 10.0 * MM_DAY_TO_M_S)


def test_a_native_series_refuses_one_value_off_its_step_count() -> None:
    with pytest.raises(ValueError, match="one value per step"):
        NativeSeries(starts=pd.date_range("2026-01-01", periods=3, freq="D"), values=[1.0])
    with pytest.raises(ValueError, match="one value per step"):
        NativeSeries(starts=pd.date_range("2026-01-01", periods=2, freq="D"), values=[1.0, 2.0])


def test_a_native_series_refuses_starts_out_of_order_or_repeated() -> None:
    starts = pd.DatetimeIndex(["2026-01-02", "2026-01-01"])
    with pytest.raises(ValueError, match="unique and increasing"):
        NativeSeries(starts=starts, values=[1.0])
    repeated = pd.DatetimeIndex(["2026-01-01", "2026-01-01"])
    with pytest.raises(ValueError, match="unique and increasing"):
        NativeSeries(starts=repeated, values=[1.0])


def _field_dataset(values: Any, index: Any) -> Any:
    """A duck field record: an xarray dataset is read here, so it is a stand-in.

    The test builds the object ``_series_of_one_field`` reads through the
    dataset property of a real ``FieldRecord``, without the data package: the
    grid is 4 by 4 pixels of 10 m over the square cell, the values laid out
    ``(time, y, x)`` with y descending.
    """
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
