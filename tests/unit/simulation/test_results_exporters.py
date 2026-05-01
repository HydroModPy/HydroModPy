"""Tests for simulation/results/exporters/ - format-specific exporters."""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.core.exceptions import UnknownFieldError
from hydromodpy.results.catalog import SimulationCatalog


@pytest.fixture
def catalog_with_data(tmp_path):
    """A catalog with one simulation containing mesh, head field, and timeseries."""
    c = SimulationCatalog(tmp_path / "workspace")
    sid = str(uuid4())

    n_cells, n_layers, n_ts = 6, 2, 3
    reg = c.register_simulation(
        sid,
        project="test",
        solver="modflownwt",
        n_cells=n_cells,
        n_layers=n_layers,
        n_timesteps=n_ts,
        crs="EPSG:2154",
    )
    if reg.zarr is not None:
        reg.zarr.close()

    # Triangle mesh (6 triangles, 7 nodes)
    verts = np.array(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [0.5, 0.8],
            [1.5, 0.8],
            [0.8, 1.8],
            [2.0, 0.4],
            [1.8, 1.6],
        ],
        dtype="float64",
    )

    # 6 cells as triangles; pad connectivity to max_vpf=4 with fill=-1
    conn = np.array(
        [
            [0, 1, 2, -1],
            [1, 3, 2, -1],
            [2, 3, 4, -1],
            [1, 5, 3, -1],
            [3, 6, 4, -1],
            [3, 5, 6, -1],
        ],
        dtype="int32",
    )

    z_intf = np.array([10.0, 5.0, 0.0])
    c.write_mesh(sid, verts, conn, z_intf)
    c.write_time(sid, np.array([0, 86400, 172800], dtype="int64"))
    c.write_crs(sid, crs_wkt="EPSG:2154", epsg_code=2154)

    rng = np.random.default_rng(42)
    for t in range(n_ts):
        head = rng.uniform(3.0, 12.0, (n_layers, n_cells))
        c.write_field(sid, "head", t, head, n_timesteps=n_ts if t == 0 else None)

    # Timeseries
    idx = pd.date_range("2020-01-01", periods=10, freq="D")
    q = pd.Series(rng.random(10), index=idx, name="discharge")
    c.write_timeseries(sid, "outlet", "discharge", q, unit="m3/s")

    yield c, sid, tmp_path
    c.close()


class TestNetCDFExport:
    def test_roundtrip(self, catalog_with_data):
        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "export.nc"
        result = catalog.export(sid, "head", "netcdf", out)
        assert result.exists()

        ds = xr.open_dataset(out, decode_times=False)
        assert "head" in ds
        assert "mesh2d" in ds
        assert "node_x" in ds
        assert "face_nodes" in ds
        assert ds["head"].dims == ("time", "layer", "n_face")
        assert ds["head"].shape == (3, 2, 6)
        ds.close()

    def test_multi_variable(self, catalog_with_data):
        catalog, sid, tmp_path = catalog_with_data
        # Write a 2D derived field
        rng = np.random.default_rng(0)
        for t in range(3):
            catalog.write_field(
                sid,
                "watertable_depth",
                t,
                rng.random(6),
                n_timesteps=3 if t == 0 else None,
                subgroup="derived",
            )

        out = tmp_path / "multi.nc"
        result = catalog.export(sid, "head,watertable_depth", "netcdf", out)
        ds = xr.open_dataset(out, decode_times=False)
        assert "head" in ds
        assert "watertable_depth" in ds
        assert ds["watertable_depth"].dims == ("time", "n_face")
        ds.close()

    def test_timestep_subset(self, catalog_with_data):
        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "subset.nc"
        result = catalog.export(sid, "head", "netcdf", out, timesteps=[0, 2])
        ds = xr.open_dataset(out, decode_times=False)
        assert ds["head"].shape[0] == 2
        np.testing.assert_array_equal(ds["time"].values, np.array([0, 172800]))
        ds.close()


class TestCSVExport:
    def test_basic(self, catalog_with_data):
        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "ts.csv"
        result = catalog.export(sid, "*", "csv", out)
        assert result.exists()
        df = pd.read_csv(out)
        assert len(df) == 10
        assert "station_id" in df.columns
        assert "variable" in df.columns
        assert df["station_id"].iloc[0] == "outlet"

    def test_filter_variable(self, catalog_with_data):
        catalog, sid, tmp_path = catalog_with_data
        # Add another variable
        idx = pd.date_range("2020-01-01", periods=5, freq="D")
        catalog.write_timeseries(
            sid,
            "outlet",
            "head",
            pd.Series(range(5), index=idx, dtype=float),
        )
        out = tmp_path / "filtered.csv"
        catalog.export(sid, "discharge", "csv", out)
        df = pd.read_csv(out)
        assert all(df["variable"] == "discharge")

    def test_empty_result(self, catalog_with_data):
        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "empty.csv"
        catalog.export(sid, "nonexistent", "csv", out)
        df = pd.read_csv(out)
        assert len(df) == 0


class TestVTUExport:
    def test_basic(self, catalog_with_data):
        import meshio

        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "field.vtu"
        result = catalog.export(sid, "head", "vtu", out, timestep=0, layer=0)
        assert result.exists()
        mesh = meshio.read(str(out))
        assert "head" in mesh.cell_data
        total_cells = sum(len(cd) for cd in mesh.cell_data["head"])
        assert total_cells == 6


class TestGeoTIFFExport:
    def test_basic(self, catalog_with_data):
        import rasterio

        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "field.tif"
        result = catalog.export(
            sid,
            "head",
            "geotiff",
            out,
            timestep=0,
            layer=0,
            resolution=0.5,
        )
        assert result.exists()
        with rasterio.open(str(out)) as src:
            assert src.count == 1
            assert src.width > 0
            assert src.height > 0
            data = src.read(1)
            # At least some valid pixels (not all nodata)
            assert np.any(data != -9999.0)


class TestShapefileExport:
    def test_basic(self, catalog_with_data):
        import geopandas as gpd

        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "cells.shp"
        result = catalog.export(
            sid,
            "head",
            "shapefile",
            out,
            timestep=0,
            layer=0,
        )
        assert result.exists()
        gdf = gpd.read_file(str(out))
        assert len(gdf) == 6
        assert "head" in gdf.columns
        assert "cell_id" in gdf.columns


class TestExportErrors:
    def test_unknown_format(self, catalog_with_data):
        catalog, sid, tmp_path = catalog_with_data
        with pytest.raises(ValueError, match="Unknown export format"):
            catalog.export(sid, "head", "parquet", tmp_path / "out.pq")

    def test_missing_variable_netcdf(self, catalog_with_data):
        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "missing.nc"
        with pytest.raises(UnknownFieldError, match="nonexistent_field"):
            catalog.export(sid, "nonexistent_field", "netcdf", out)
