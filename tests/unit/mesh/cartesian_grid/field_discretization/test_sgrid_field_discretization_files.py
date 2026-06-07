"""Unit tests for file-referenced field discretization on structured grids.

Covers: GeoTIFF reprojection, NetCDF load + discretize, multi-band GeoTIFF.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_field_discretization import (
    discretize_fields_on_sgrid,
)

from ._test_sgrid_field_discretization_builders import (
    MM_DAY_TO_M_S,
    _make_sgrid,
    _make_simulation_window,
)

pytestmark = pytest.mark.fast


# ---------------------------------------------------------------------------
# 4. GeoTIFF file reference - steady
# ---------------------------------------------------------------------------


class TestGeoTIFFDiscretization:
    def test_geotiff_static_field_steady(self, tmp_path: Path):
        """A GeoTIFF with uniform recharge should produce correct m/s values."""
        import rasterio
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
# 13. Multi-band GeoTIFF
# ---------------------------------------------------------------------------


class TestMultiBandGeoTIFF:
    def test_multiband_tif_produces_per_band_arrays(self, tmp_path: Path):
        """A multi-band GeoTIFF should produce one array per band."""
        import rasterio
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
