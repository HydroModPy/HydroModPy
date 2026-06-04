"""Unit tests for point-to-grid interpolation and field spatial-mean reduction.

Covers: single/multi-station discretization, IDW gradients and exact matches,
unlocated points, and the field-to-homogeneous spatial-mean helper.
"""

from __future__ import annotations

import warnings
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_field_discretization import (
    discretize_points_on_sgrid,
    spatial_mean_from_fields,
)

from ._test_sgrid_field_discretization_builders import (
    MM_DAY_TO_M_S,
    _make_sgrid,
    _make_static_field_record,
    _make_temporal_field_record,
)

pytestmark = pytest.mark.fast


# ---------------------------------------------------------------------------
# 11. Point-to-grid interpolation
# ---------------------------------------------------------------------------


def _make_located_point_record(
    station_id: str,
    x: float,
    y: float,
    value: float,
    start_date: str = "2020-01-01",
    n_days: int = 31,
    unit: str = "mm/day",
) -> PointRecord:
    """Create a PointRecord with a constant value and location."""
    dates = pd.date_range(start_date, periods=n_days, freq="D")
    df = pd.DataFrame({"datetime": dates, "value": value})
    return PointRecord(
        station_id=station_id,
        variable="recharge",
        source="test",
        unit=unit,
        frequency="D",
        data=df,
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, 1) + timedelta(days=n_days - 1),
        location=StationLocation(id=station_id, x=x, y=y, crs="EPSG:2154"),
    )


class TestPointToGridInterpolation:
    def test_single_station_nearest_fills_grid(self):
        """A single station should fill the entire grid with its value."""
        nrow, ncol = 3, 4
        dx, dy = 10.0, 10.0
        sgrid = _make_sgrid(nrow, ncol, dx=dx, dy=dy)

        pt = _make_located_point_record("S1", x=25.0, y=15.0, value=8.0, unit="mm/day")
        result = discretize_points_on_sgrid(
            load_result=LoadResult(points=[pt]),
            sgrid=sgrid,
            nper=1,
            method="nearest",
        )

        expected_m_s = 8.0 * MM_DAY_TO_M_S
        assert result[0].shape == (nrow, ncol)
        assert np.allclose(result[0], expected_m_s, rtol=1e-6)

    def test_two_stations_idw_gradient(self):
        """Two stations at opposite ends should produce a spatial gradient."""
        nrow, ncol = 1, 5
        dx, dy = 10.0, 10.0
        sgrid = _make_sgrid(nrow, ncol, dx=dx, dy=dy)

        pt_west = _make_located_point_record("W", x=5.0, y=5.0, value=10.0, unit="mm/day")
        pt_east = _make_located_point_record("E", x=45.0, y=5.0, value=20.0, unit="mm/day")

        result = discretize_points_on_sgrid(
            load_result=LoadResult(points=[pt_west, pt_east]),
            sgrid=sgrid,
            nper=1,
            method="idw",
        )

        arr = result[0]
        assert arr.shape == (nrow, ncol)
        # IDW: west cell closer to W station → lower value,
        # east cell closer to E station → higher value.
        assert arr[0, 0] < arr[0, -1]  # gradient west→east
        # Both values should be between 10 and 20 mm/day in m/s.
        assert np.all(arr >= 10.0 * MM_DAY_TO_M_S * 0.99)
        assert np.all(arr <= 20.0 * MM_DAY_TO_M_S * 1.01)

    def test_idw_exact_match_emits_no_runtime_warning(self):
        """IDW should not emit a divide-by-zero warning on exact station matches."""
        nrow, ncol = 1, 3
        dx, dy = 10.0, 10.0
        sgrid = _make_sgrid(nrow, ncol, dx=dx, dy=dy)

        pt_west = _make_located_point_record("W", x=5.0, y=5.0, value=10.0, unit="mm/day")
        pt_east = _make_located_point_record("E", x=25.0, y=5.0, value=20.0, unit="mm/day")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", RuntimeWarning)
            result = discretize_points_on_sgrid(
                load_result=LoadResult(points=[pt_west, pt_east]),
                sgrid=sgrid,
                nper=1,
                method="idw",
            )

        runtime_warnings = [
            warning for warning in caught if issubclass(warning.category, RuntimeWarning)
        ]
        assert runtime_warnings == []
        arr = result[0]
        assert arr.shape == (nrow, ncol)
        assert arr[0, 0] == pytest.approx(10.0 * MM_DAY_TO_M_S)
        assert arr[0, -1] == pytest.approx(20.0 * MM_DAY_TO_M_S)

    def test_no_located_points_returns_zeros(self):
        """PointRecords without locations should produce zeros."""
        nrow, ncol = 2, 2
        sgrid = _make_sgrid(nrow, ncol)

        dates = pd.date_range("2020-01-01", periods=5, freq="D")
        pt = PointRecord(
            station_id="nocoord",
            variable="recharge",
            source="test",
            unit="mm/day",
            frequency="D",
            data=pd.DataFrame({"datetime": dates, "value": 5.0}),
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 1, 5),
            location=None,
        )

        result = discretize_points_on_sgrid(
            load_result=LoadResult(points=[pt]),
            sgrid=sgrid,
            nper=1,
        )

        assert np.all(result[0] == 0.0)


# ---------------------------------------------------------------------------
# 12. Spatial mean (field → homogeneous reduction)
# ---------------------------------------------------------------------------


class TestSpatialMeanFromFields:
    def test_static_field_spatial_mean(self):
        """Spatial mean of a uniform static field should be the field value."""
        nrow, ncol = 3, 4
        field_rec = _make_static_field_record(nrow, ncol, value=7.5, unit="mm/day")

        series = spatial_mean_from_fields(LoadResult(fields=[field_rec]))

        assert series is not None
        assert len(series) == 1
        assert series.iloc[0] == pytest.approx(7.5, rel=1e-10)

    def test_temporal_field_spatial_mean_per_timestep(self):
        """Spatial mean of a temporal field should produce one value per timestep."""
        nrow, ncol = 2, 3
        # 3 days: 1.0, 2.0, 3.0 mm/day
        field_rec = _make_temporal_field_record(
            nrow,
            ncol,
            values_per_day=[1.0, 2.0, 3.0],
            start_date="2020-01-01",
            unit="mm/day",
        )

        series = spatial_mean_from_fields(LoadResult(fields=[field_rec]))

        assert series is not None
        assert len(series) == 3
        assert series.iloc[0] == pytest.approx(1.0, rel=1e-10)
        assert series.iloc[1] == pytest.approx(2.0, rel=1e-10)
        assert series.iloc[2] == pytest.approx(3.0, rel=1e-10)

    def test_empty_load_result_returns_none(self):
        assert spatial_mean_from_fields(LoadResult()) is None
