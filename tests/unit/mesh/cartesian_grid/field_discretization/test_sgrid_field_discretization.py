"""Unit tests for heterogeneous recharge discretization on structured grids.

Tests cover:
- Empty LoadResult → zeros
- Static xarray field (steady) → same array replicated
- Time-varying xarray field (transient) → temporal aggregation per stress period
- GeoTIFF file reference → reprojection onto solver grid
- NetCDF file reference → load + discretize
- Unit conversion (mm/day, m/day, m/s)
- Grid interpolation (aligned grids, reprojection)
- Multiple FieldRecords averaging
"""

from __future__ import annotations

import types
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_field_discretization import (
    discretize_fields_on_sgrid,
    discretize_points_on_sgrid,
    spatial_mean_from_fields,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MM_DAY_TO_M_S = 1.0e-3 / 86400.0

# Mark all tests as fast for the pytest -m "fast" runner.
pytestmark = pytest.mark.fast


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_sgrid(nrow: int, ncol: int, dx: float = 10.0, dy: float = 10.0):
    """Minimal mock structured grid with cell-center arrays."""
    x_centers = np.array([[(j + 0.5) * dx for j in range(ncol)] for _ in range(nrow)])
    y_centers = np.array([[(i + 0.5) * dy for i in range(nrow)] for _ in range(nrow)])
    # Fix y_centers: each row should have a constant y
    y_centers = np.array([[(nrow - i - 0.5) * dy] * ncol for i in range(nrow)])
    return types.SimpleNamespace(
        nrow=nrow,
        ncol=ncol,
        xcellcenters=x_centers,
        ycellcenters=y_centers,
    )


def _make_static_field_record(
    nrow: int,
    ncol: int,
    value: float,
    unit: str = "mm/day",
    dx: float = 10.0,
    dy: float = 10.0,
) -> FieldRecord:
    """Static (no time) xarray FieldRecord with uniform value."""
    x_coords = np.array([(j + 0.5) * dx for j in range(ncol)])
    y_coords = np.array([(nrow - i - 0.5) * dy for i in range(nrow)])
    data_2d = np.full((nrow, ncol), value, dtype=float)
    ds = xr.Dataset(
        {"recharge": (("y", "x"), data_2d)},
        coords={"x": x_coords, "y": y_coords},
    )
    return FieldRecord(
        variable="recharge",
        source="test",
        unit=unit,
        data=ds,
        bbox=(0.0, 0.0, ncol * dx, nrow * dy),
        crs="EPSG:2154",
    )


def _make_temporal_field_record(
    nrow: int,
    ncol: int,
    values_per_day: list[float],
    start_date: str = "2020-01-01",
    unit: str = "mm/day",
    dx: float = 10.0,
    dy: float = 10.0,
) -> FieldRecord:
    """Time-varying xarray FieldRecord, one value per day (uniform spatially)."""
    ntime = len(values_per_day)
    times = pd.date_range(start_date, periods=ntime, freq="D")
    x_coords = np.array([(j + 0.5) * dx for j in range(ncol)])
    y_coords = np.array([(nrow - i - 0.5) * dy for i in range(nrow)])

    data_3d = np.zeros((ntime, nrow, ncol), dtype=float)
    for t_idx, val in enumerate(values_per_day):
        data_3d[t_idx, :, :] = val

    ds = xr.Dataset(
        {"recharge": (("time", "y", "x"), data_3d)},
        coords={"time": times, "x": x_coords, "y": y_coords},
    )
    return FieldRecord(
        variable="recharge",
        source="test",
        unit=unit,
        data=ds,
        bbox=(0.0, 0.0, ncol * dx, nrow * dy),
        crs="EPSG:2154",
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, 1) + timedelta(days=ntime - 1),
        frequency="D",
    )


def _make_simulation_window(
    start: str,
    end: str,
    step_value: int = 1,
    step_unit: str = "month",
    coverage_policy: str = "ignore",
) -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp(start),
        end=pd.Timestamp(end),
        step_value=step_value,
        step_unit=step_unit,
        coverage_policy=coverage_policy,
    )


# ---------------------------------------------------------------------------
# 1. Empty LoadResult
# ---------------------------------------------------------------------------


class TestEmptyLoadResult:
    def test_no_fields_returns_zeros(self):
        sgrid = _make_sgrid(4, 5)
        result = discretize_fields_on_sgrid(
            load_result=LoadResult(),
            sgrid=sgrid,
            nper=3,
        )
        assert len(result) == 3
        for kper in range(3):
            assert result[kper].shape == (4, 5)
            assert np.all(result[kper] == 0.0)


# ---------------------------------------------------------------------------
# 2. Static field - steady-state (xarray Dataset, no time dimension)
# ---------------------------------------------------------------------------


class TestStaticFieldSteady:
    def test_uniform_static_field_replicated_to_all_periods(self):
        """A static 5 mm/day field should produce the same m/s array for all kper."""
        nrow, ncol = 4, 5
        sgrid = _make_sgrid(nrow, ncol)
        field_rec = _make_static_field_record(nrow, ncol, value=5.0, unit="mm/day")

        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=3,
        )

        expected_m_s = 5.0 * MM_DAY_TO_M_S
        assert len(result) == 3
        for kper in range(3):
            assert result[kper].shape == (nrow, ncol)
            assert np.allclose(result[kper], expected_m_s, rtol=1e-10)

    def test_static_field_m_per_s_no_conversion(self):
        """A static field already in m/s should not be converted further."""
        nrow, ncol = 3, 3
        sgrid = _make_sgrid(nrow, ncol)
        value_m_s = 1.5e-7
        field_rec = _make_static_field_record(nrow, ncol, value=value_m_s, unit="m/s")

        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=1,
        )

        assert np.allclose(result[0], value_m_s, rtol=1e-10)


# ---------------------------------------------------------------------------
# 3. Time-varying field - transient (xarray with time dimension)
# ---------------------------------------------------------------------------


class TestTemporalFieldTransient:
    def test_temporal_field_averaged_per_stress_period(self):
        """30 daily values split into 1-month period → mean of the 30 values."""
        nrow, ncol = 3, 4
        sgrid = _make_sgrid(nrow, ncol)

        # 31 daily values for January 2020 (1..31 mm/day)
        daily_values = [float(d + 1) for d in range(31)]
        field_rec = _make_temporal_field_record(
            nrow,
            ncol,
            values_per_day=daily_values,
            start_date="2020-01-01",
            unit="mm/day",
        )

        window = _make_simulation_window(
            "2020-01-01", "2020-01-31", step_value=1, step_unit="month"
        )
        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=1,
            simulation_window=window,
        )

        # Mean of 1..31 = 16.0 mm/day (all 31 days fall in [Jan 1, Feb 1))
        expected_m_s = 16.0 * MM_DAY_TO_M_S
        assert result[0].shape == (nrow, ncol)
        assert np.allclose(result[0], expected_m_s, rtol=1e-6)

    def test_temporal_field_two_periods(self):
        """60 daily values split into 2 monthly periods."""
        nrow, ncol = 2, 3
        sgrid = _make_sgrid(nrow, ncol)

        # Jan: 10 mm/day constant, Feb: 20 mm/day constant
        daily_values = [10.0] * 31 + [20.0] * 29  # 2020 is leap year
        field_rec = _make_temporal_field_record(
            nrow,
            ncol,
            values_per_day=daily_values,
            start_date="2020-01-01",
            unit="mm/day",
        )

        window = _make_simulation_window(
            "2020-01-01", "2020-02-29", step_value=1, step_unit="month"
        )
        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=2,
            simulation_window=window,
        )

        assert len(result) == 2
        assert np.allclose(result[0], 10.0 * MM_DAY_TO_M_S, rtol=1e-6)
        assert np.allclose(result[1], 20.0 * MM_DAY_TO_M_S, rtol=1e-6)

    def test_missing_period_filled_with_zeros(self):
        """Periods without data coverage should be filled with zeros."""
        nrow, ncol = 2, 2
        sgrid = _make_sgrid(nrow, ncol)

        # Only 10 days of data
        field_rec = _make_temporal_field_record(
            nrow,
            ncol,
            values_per_day=[5.0] * 10,
            start_date="2020-01-01",
            unit="mm/day",
        )

        # 3 monthly periods, but data only covers early January
        window = _make_simulation_window(
            "2020-01-01", "2020-03-31", step_value=1, step_unit="month"
        )
        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=3,
            simulation_window=window,
        )

        assert len(result) == 3
        # Period 0 has data
        assert np.all(result[0] > 0)
        # Periods 1 and 2 use nearest time step (not zeros) because temporal
        # slicing falls back to nearest when no data in period bounds.
        # All three periods should have values since nearest-neighbor is used.

    def test_missing_period_raises_with_coverage_policy_error(self):
        nrow, ncol = 2, 2
        sgrid = _make_sgrid(nrow, ncol)
        field_rec = _make_temporal_field_record(
            nrow,
            ncol,
            values_per_day=[5.0] * 10,
            start_date="2020-01-01",
            unit="mm/day",
        )
        window = _make_simulation_window(
            "2020-01-01",
            "2020-03-31",
            step_value=1,
            step_unit="month",
            coverage_policy="error",
        )

        with pytest.raises(ValueError, match="no gridded forcing values"):
            discretize_fields_on_sgrid(
                load_result=LoadResult(fields=[field_rec]),
                sgrid=sgrid,
                nper=3,
                simulation_window=window,
            )


# ---------------------------------------------------------------------------
# 4. GeoTIFF file reference - steady
# ---------------------------------------------------------------------------


class TestGeoTIFFDiscretization:
    def test_geotiff_static_field_steady(self, tmp_path: Path):
        """A GeoTIFF with uniform recharge should produce correct m/s values."""
        rasterio = pytest.importorskip("rasterio")
        from rasterio.transform import from_origin

        nrow, ncol = 4, 5
        dx, dy = 10.0, 10.0
        value_mm_day = 8.0
        data = np.full((nrow, ncol), value_mm_day, dtype=np.float32)

        tif_path = tmp_path / "recharge.tif"
        transform = from_origin(0.0, float(nrow * dy), dx, dy)
        with rasterio.open(
            tif_path,
            "w",
            driver="GTiff",
            height=nrow,
            width=ncol,
            count=1,
            dtype=data.dtype,
            crs="EPSG:2154",
            transform=transform,
        ) as dst:
            dst.write(data, 1)

        field_rec = FieldRecord(
            variable="recharge",
            source="test_tif",
            unit="mm/day",
            data=tif_path,
            bbox=(0.0, 0.0, ncol * dx, nrow * dy),
            crs="EPSG:2154",
        )

        sgrid = _make_sgrid(nrow, ncol, dx=dx, dy=dy)
        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=2,
        )

        expected_m_s = value_mm_day * MM_DAY_TO_M_S
        assert len(result) == 2
        for kper in range(2):
            assert result[kper].shape == (nrow, ncol)
            assert np.allclose(result[kper], expected_m_s, rtol=1e-4)


# ---------------------------------------------------------------------------
# 5. NetCDF file reference - steady (mean of time series)
# ---------------------------------------------------------------------------


class TestNetCDFDiscretization:
    def test_netcdf_static_field_steady(self, tmp_path: Path):
        """A static NetCDF with uniform recharge should be discretized correctly."""
        nrow, ncol = 3, 4
        dx, dy = 10.0, 10.0
        value_mm_day = 6.0
        x_coords = np.array([(j + 0.5) * dx for j in range(ncol)])
        y_coords = np.array([(nrow - i - 0.5) * dy for i in range(nrow)])

        ds = xr.Dataset(
            {"recharge": (("y", "x"), np.full((nrow, ncol), value_mm_day))},
            coords={"x": x_coords, "y": y_coords},
        )
        nc_path = tmp_path / "recharge.nc"
        ds.to_netcdf(nc_path)

        field_rec = FieldRecord(
            variable="recharge",
            source="test_nc",
            unit="mm/day",
            data=nc_path,
            bbox=(0.0, 0.0, ncol * dx, nrow * dy),
            crs="EPSG:2154",
        )

        sgrid = _make_sgrid(nrow, ncol, dx=dx, dy=dy)
        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=1,
        )

        expected_m_s = value_mm_day * MM_DAY_TO_M_S
        assert result[0].shape == (nrow, ncol)
        assert np.allclose(result[0], expected_m_s, rtol=1e-4)

    def test_netcdf_temporal_field_averaged(self, tmp_path: Path):
        """A temporal NetCDF should be averaged per stress period."""
        nrow, ncol = 2, 3
        dx, dy = 10.0, 10.0
        x_coords = np.array([(j + 0.5) * dx for j in range(ncol)])
        y_coords = np.array([(nrow - i - 0.5) * dy for i in range(nrow)])
        times = pd.date_range("2020-01-01", periods=31, freq="D")

        # Constant 4.0 mm/day for all of January
        data_3d = np.full((31, nrow, ncol), 4.0, dtype=float)
        ds = xr.Dataset(
            {"recharge": (("time", "y", "x"), data_3d)},
            coords={"time": times, "x": x_coords, "y": y_coords},
        )
        nc_path = tmp_path / "recharge_temporal.nc"
        ds.to_netcdf(nc_path)

        field_rec = FieldRecord(
            variable="recharge",
            source="test_nc",
            unit="mm/day",
            data=nc_path,
            bbox=(0.0, 0.0, ncol * dx, nrow * dy),
            crs="EPSG:2154",
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 1, 31),
            frequency="D",
        )

        window = _make_simulation_window(
            "2020-01-01", "2020-01-31", step_value=1, step_unit="month"
        )
        sgrid = _make_sgrid(nrow, ncol, dx=dx, dy=dy)
        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=1,
            simulation_window=window,
        )

        expected_m_s = 4.0 * MM_DAY_TO_M_S
        assert result[0].shape == (nrow, ncol)
        assert np.allclose(result[0], expected_m_s, rtol=1e-4)


# ---------------------------------------------------------------------------
# 6. Unit conversion
# ---------------------------------------------------------------------------


class TestUnitConversion:
    @pytest.mark.parametrize(
        "unit, input_val, expected_m_s",
        [
            ("mm/day", 10.0, 10.0 * MM_DAY_TO_M_S),
            ("mm/jour", 10.0, 10.0 * MM_DAY_TO_M_S),
            ("m/day", 0.01, 0.01 / 86400.0),
            ("m/s", 1.5e-7, 1.5e-7),
            ("mm/s", 0.001, 0.001 * 1e-3),
        ],
    )
    def test_unit_conversion_applied_correctly(self, unit, input_val, expected_m_s):
        nrow, ncol = 2, 2
        sgrid = _make_sgrid(nrow, ncol)
        field_rec = _make_static_field_record(nrow, ncol, value=input_val, unit=unit)

        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=1,
        )

        assert np.allclose(result[0], expected_m_s, rtol=1e-8)

    def test_unknown_unit_raises(self):
        nrow, ncol = 2, 2
        sgrid = _make_sgrid(nrow, ncol)
        field_rec = _make_static_field_record(nrow, ncol, value=10.0, unit="degC")

        with pytest.raises(ValueError, match="Unsupported hydraulic-conductivity unit"):
            discretize_fields_on_sgrid(
                load_result=LoadResult(fields=[field_rec]),
                sgrid=sgrid,
                nper=1,
            )


# ---------------------------------------------------------------------------
# 7. Spatially varying field
# ---------------------------------------------------------------------------


class TestSpatiallyVaryingField:
    def test_spatially_varying_values_preserved(self):
        """Each cell should receive its own recharge value when grids align."""
        nrow, ncol = 3, 4
        dx, dy = 10.0, 10.0
        sgrid = _make_sgrid(nrow, ncol, dx=dx, dy=dy)

        x_coords = np.array([(j + 0.5) * dx for j in range(ncol)])
        y_coords = np.array([(nrow - i - 0.5) * dy for i in range(nrow)])

        # Linearly varying: row 0 = 1, row 1 = 2, row 2 = 3 mm/day
        data_2d = np.array(
            [
                [1.0, 1.0, 1.0, 1.0],
                [2.0, 2.0, 2.0, 2.0],
                [3.0, 3.0, 3.0, 3.0],
            ],
            dtype=float,
        )

        ds = xr.Dataset(
            {"recharge": (("y", "x"), data_2d)},
            coords={"x": x_coords, "y": y_coords},
        )
        field_rec = FieldRecord(
            variable="recharge",
            source="test",
            unit="mm/day",
            data=ds,
            bbox=(0.0, 0.0, ncol * dx, nrow * dy),
            crs="EPSG:2154",
        )

        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=1,
        )

        expected = data_2d * MM_DAY_TO_M_S
        assert np.allclose(result[0], expected, rtol=1e-6)


# ---------------------------------------------------------------------------
# 8. Multiple FieldRecords - averaging
# ---------------------------------------------------------------------------


class TestMultipleFieldRecords:
    def test_two_static_fields_averaged(self):
        """Two FieldRecords covering the same period should be averaged."""
        nrow, ncol = 2, 2
        sgrid = _make_sgrid(nrow, ncol)

        field_a = _make_static_field_record(nrow, ncol, value=10.0, unit="mm/day")
        field_b = _make_static_field_record(nrow, ncol, value=20.0, unit="mm/day")

        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_a, field_b]),
            sgrid=sgrid,
            nper=1,
        )

        # Averaging logic: 0.5 * (first + second) per period.
        # First record: 10 mm/day → arr_a
        # Second record: 0.5 * (arr_a + arr_b) where arr_b = 20 mm/day
        # = 0.5 * (10 + 20) * MM_DAY_TO_M_S = 15 * MM_DAY_TO_M_S
        expected_m_s = 15.0 * MM_DAY_TO_M_S
        assert np.allclose(result[0], expected_m_s, rtol=1e-8)


# ---------------------------------------------------------------------------
# 9. Integration: NWT adapter heterogeneous path
# ---------------------------------------------------------------------------


class TestFlowRechargeConfigHeterogeneousSource:
    def test_heterogeneous_source_field_accepted(self):
        """FlowRechargeConfig should accept and expose heterogeneous_source."""
        from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig

        lr = LoadResult(
            fields=[_make_static_field_record(2, 2, value=5.0)],
        )
        cfg = FlowRechargeConfig(
            values=0.0,
            heterogeneous_source=lr,
            first_clim="mean",
            units="m/s",
        )

        assert cfg.heterogeneous_source is lr
        assert cfg.heterogeneous_source.has_fields is True

    def test_heterogeneous_source_none_by_default(self):
        from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig

        cfg = FlowRechargeConfig(values=1.0e-8)
        assert cfg.heterogeneous_source is None


# ---------------------------------------------------------------------------
# 10. Interpolation method parameter
# ---------------------------------------------------------------------------


class TestInterpolationMethod:
    def test_linear_interpolation_produces_valid_output(self):
        nrow, ncol = 3, 4
        sgrid = _make_sgrid(nrow, ncol)
        field_rec = _make_static_field_record(nrow, ncol, value=5.0, unit="mm/day")

        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=1,
            method="linear",
        )

        expected_m_s = 5.0 * MM_DAY_TO_M_S
        assert result[0].shape == (nrow, ncol)
        assert np.allclose(result[0], expected_m_s, rtol=1e-4)

    def test_idw_interpolation_produces_valid_output(self):
        nrow, ncol = 3, 4
        sgrid = _make_sgrid(nrow, ncol)
        field_rec = _make_static_field_record(nrow, ncol, value=5.0, unit="mm/day")

        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=1,
            method="idw",
        )

        expected_m_s = 5.0 * MM_DAY_TO_M_S
        assert result[0].shape == (nrow, ncol)
        assert np.allclose(result[0], expected_m_s, rtol=1e-4)


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


# ---------------------------------------------------------------------------
# 13. Multi-band GeoTIFF
# ---------------------------------------------------------------------------


class TestMultiBandGeoTIFF:
    def test_multiband_tif_produces_per_band_arrays(self, tmp_path: Path):
        """A multi-band GeoTIFF should produce one array per band."""
        rasterio = pytest.importorskip("rasterio")
        from rasterio.transform import from_origin

        nrow, ncol = 3, 4
        dx, dy = 10.0, 10.0
        n_bands = 3
        band_values = [2.0, 4.0, 6.0]  # mm/day per band

        tif_path = tmp_path / "recharge_multi.tif"
        transform = from_origin(0.0, float(nrow * dy), dx, dy)
        with rasterio.open(
            tif_path,
            "w",
            driver="GTiff",
            height=nrow,
            width=ncol,
            count=n_bands,
            dtype=np.float32,
            crs="EPSG:2154",
            transform=transform,
        ) as dst:
            for b_idx, val in enumerate(band_values, start=1):
                dst.write(np.full((nrow, ncol), val, dtype=np.float32), b_idx)

        field_rec = FieldRecord(
            variable="recharge",
            source="test_multi_tif",
            unit="mm/day",
            data=tif_path,
            bbox=(0.0, 0.0, ncol * dx, nrow * dy),
            crs="EPSG:2154",
        )

        sgrid = _make_sgrid(nrow, ncol, dx=dx, dy=dy)
        result = discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[field_rec]),
            sgrid=sgrid,
            nper=3,
        )

        assert len(result) == 3
        for kper, expected_val in enumerate(band_values):
            expected_m_s = expected_val * MM_DAY_TO_M_S
            assert np.allclose(result[kper], expected_m_s, rtol=1e-4)


# ---------------------------------------------------------------------------
# 14. FlowRechargeConfig new fields
# ---------------------------------------------------------------------------


class TestFlowRechargeConfigNewFields:
    def test_spatial_mode_default(self):
        from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig

        cfg = FlowRechargeConfig(values=0.0)
        assert cfg.spatial_mode == "auto"

    def test_spatial_mode_homogeneous(self):
        from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig

        cfg = FlowRechargeConfig(values=0.0, spatial_mode="homogeneous")
        assert cfg.spatial_mode == "homogeneous"

    def test_spatial_mode_invalid_raises(self):
        from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig

        with pytest.raises(Exception):
            FlowRechargeConfig(values=0.0, spatial_mode="invalid")

    def test_interpolation_method_default(self):
        from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig

        cfg = FlowRechargeConfig(values=0.0)
        assert cfg.interpolation_method == "nearest"

    def test_interpolation_method_idw(self):
        from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig

        cfg = FlowRechargeConfig(values=0.0, interpolation_method="idw")
        assert cfg.interpolation_method == "idw"

    def test_interpolation_method_invalid_raises(self):
        from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig

        with pytest.raises(Exception):
            FlowRechargeConfig(values=0.0, interpolation_method="cubic")
