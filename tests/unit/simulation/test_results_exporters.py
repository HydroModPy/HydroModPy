"""Tests for simulation/results/exporters/ - format-specific exporters."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from pydantic import ValidationError

from hydromodpy.core.config_kit.export_spec import ExportSpec
from hydromodpy.core.exceptions import UnknownFieldError
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog_with_data(tmp_path):
    """A catalog with one simulation containing mesh, head field, and timeseries."""
    with simulation_catalog(tmp_path / "workspace") as c:
        sid = str(uuid4())

        n_cells, n_layers, n_ts = 6, 2, 3
        reg = c.register_simulation(
            sid,
            project="test",
            solver="modflow_nwt",
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


class TestNetCDFExport:
    def test_roundtrip(self, catalog_with_data):
        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "export.nc"
        result = catalog.export(sid, ExportSpec(var="head", fmt="netcdf", dest=out))
        assert result.exists()

        ds = xr.open_dataset(out, decode_times=False)
        assert "mesh2d" in ds
        assert "node_x" in ds
        assert "face_nodes" in ds
        # MDAL, what QGIS reads a mesh with, binds a dataset to the face
        # dimension and ignores an array carrying a third one, so a layered
        # field is written one variable per layer.
        assert "head" not in ds
        assert ds["head_layer1"].dims == ("time", "n_face")
        assert ds["head_layer1"].shape == (3, 6)
        assert ds["head_layer2"].shape == (3, 6)
        assert "layer" not in ds.dims
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
        catalog.export(sid, ExportSpec(var=["head", "watertable_depth"], fmt="netcdf", dest=out))
        ds = xr.open_dataset(out, decode_times=False)
        assert "head_layer1" in ds
        assert "watertable_depth" in ds
        assert ds["watertable_depth"].dims == ("time", "n_face")
        ds.close()

    def test_timestep_subset(self, catalog_with_data):
        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "subset.nc"
        catalog.export(sid, ExportSpec(var="head", fmt="netcdf", dest=out, time=[0, 2]))
        ds = xr.open_dataset(out, decode_times=False)
        assert ds["head_layer1"].shape[0] == 2
        np.testing.assert_array_equal(ds["time"].values, np.array([0, 172800]))
        ds.close()


class TestCSVExport:
    def test_basic(self, catalog_with_data):
        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "ts.csv"
        result = catalog.export(sid, ExportSpec(var="*", fmt="csv", dest=out))
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
        catalog.export(sid, ExportSpec(var="discharge", fmt="csv", dest=out))
        df = pd.read_csv(out)
        assert all(df["variable"] == "discharge")

    def test_empty_result(self, catalog_with_data):
        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "empty.csv"
        catalog.export(sid, ExportSpec(var="nonexistent", fmt="csv", dest=out))
        df = pd.read_csv(out)
        assert len(df) == 0


class TestVTUExport:
    def test_basic(self, catalog_with_data):
        meshio = pytest.importorskip("meshio")

        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "field.vtu"
        result = catalog.export(sid, ExportSpec(var="head", fmt="vtu", dest=out, time=0, layer=0))
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
            ExportSpec(var="head", fmt="geotiff", dest=out, time=0, layer=0, resolution=0.5),
        )
        assert result.exists()
        with rasterio.open(str(out)) as src:
            assert src.count == 1
            assert src.width > 0
            assert src.height > 0
            data = src.read(1)
            # At least some valid pixels (not all nodata)
            assert np.any(data != -9999.0)

    def test_geotiff_export_is_cog_compliant(self, catalog_with_data):
        """Output rasters are tiled, zstd-compressed and carry HMP_* tags."""
        import rasterio

        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "field_cog.tif"
        catalog.export(
            sid,
            ExportSpec(var="head", fmt="geotiff", dest=out, time=0, layer=0, resolution=0.5),
        )
        with rasterio.open(str(out)) as src:
            profile = src.profile
            assert profile.get("tiled") is True
            assert profile.get("blockxsize") == 512
            assert profile.get("blockysize") == 512
            compression = src.compression.value if src.compression else ""
            assert "zstd" in compression.lower()
            tags = src.tags()
            assert tags.get("HMP_SIM_ID") == str(sid)
            assert tags.get("HMP_VARIABLE") == "head"
            assert "HMP_TIMESTAMP" in tags


class TestShapefileExport:
    def test_basic(self, catalog_with_data):
        import geopandas as gpd

        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "cells.shp"
        result = catalog.export(
            sid,
            ExportSpec(var="head", fmt="shapefile", dest=out, time=0, layer=0),
        )
        assert result.exists()
        gdf = gpd.read_file(str(out))
        assert len(gdf) == 6
        assert "head" in gdf.columns
        assert "cell_id" in gdf.columns


class TestExportErrors:
    def test_unknown_format(self, catalog_with_data):
        _catalog, _sid, tmp_path = catalog_with_data
        # An unknown format is rejected at spec construction, before any I/O.
        with pytest.raises(ValidationError):
            ExportSpec(var="head", fmt="parquet", dest=tmp_path / "out.pq")

    def test_missing_variable_netcdf(self, catalog_with_data):
        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "missing.nc"
        with pytest.raises(UnknownFieldError, match="nonexistent_field"):
            catalog.export(sid, ExportSpec(var="nonexistent_field", fmt="netcdf", dest=out))


class TestNetCDFForQgis:
    """What MDAL, the driver QGIS reads a mesh with, needs to find in the file."""

    def test_crs_is_restated_the_way_mdal_reads_it(self, catalog_with_data):
        from pyproj import CRS

        catalog, sid, tmp_path = catalog_with_data
        catalog.write_crs(sid, crs_wkt=CRS.from_epsg(2154).to_wkt(), epsg_code=2154)

        out = tmp_path / "crs.nc"
        catalog.export(sid, ExportSpec(var="head", fmt="netcdf", dest=out))

        ds = xr.open_dataset(out, decode_times=False)
        try:
            # The CF grid mapping stays, and carries WKT2 as it should.
            assert ds["crs"].attrs["crs_wkt"].startswith("PROJCRS[")
            # MDAL looks this variable up by name and parses WKT1 only: handed
            # WKT2 it keeps no CRS at all and QGIS draws the mesh nowhere near
            # the catchment.
            mdal = ds["projected_coordinate_system"].attrs
            assert mdal["epsg"] == 2154
            assert mdal["wkt"].startswith("PROJCS[")
        finally:
            ds.close()

    def test_crs_without_a_readable_wkt_still_carries_the_epsg_code(self, catalog_with_data):
        catalog, sid, tmp_path = catalog_with_data
        # The fixture stores "EPSG:2154" in place of a WKT, which pyproj cannot
        # turn into WKT1. The code has to survive on its own.
        out = tmp_path / "crs_epsg_only.nc"
        catalog.export(sid, ExportSpec(var="head", fmt="netcdf", dest=out))

        ds = xr.open_dataset(out, decode_times=False)
        try:
            mdal = ds["projected_coordinate_system"].attrs
            assert mdal["epsg"] == 2154
            assert "wkt" not in mdal
        finally:
            ds.close()

    def test_face_coordinates_are_declared_on_the_mesh(self, catalog_with_data):
        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "mesh.nc"
        catalog.export(sid, ExportSpec(var="head", fmt="netcdf", dest=out))

        ds = xr.open_dataset(out, decode_times=False)
        try:
            # Undeclared, the centroids read as two datasets to plot.
            assert ds["mesh2d"].attrs["face_coordinates"] == "face_x face_y"
        finally:
            ds.close()

    def test_a_failed_export_leaves_the_previous_file_alone(self, catalog_with_data, monkeypatch):
        catalog, sid, tmp_path = catalog_with_data
        out = tmp_path / "kept.nc"
        catalog.export(sid, ExportSpec(var="head", fmt="netcdf", dest=out))
        before = out.read_bytes()

        def fail_midway(self, path, *args, **kwargs):
            Path(path).write_bytes(b"half a file")
            raise OSError("no space left on device")

        monkeypatch.setattr(xr.Dataset, "to_netcdf", fail_midway)
        with pytest.raises(OSError):
            catalog.export(sid, ExportSpec(var="head", fmt="netcdf", dest=out))

        assert out.read_bytes() == before
        assert not (tmp_path / "kept.nc.tmp").exists()

    def test_a_single_layer_field_keeps_its_bare_name(self, catalog_with_data):
        catalog, sid, tmp_path = catalog_with_data
        rng = np.random.default_rng(1)
        for t in range(3):
            catalog.write_field(
                sid,
                "recharge",
                t,
                rng.random((1, 6)),
                n_timesteps=3 if t == 0 else None,
                subgroup="budget",
            )

        out = tmp_path / "one_layer.nc"
        catalog.export(sid, ExportSpec(var="recharge", fmt="netcdf", dest=out))

        ds = xr.open_dataset(out, decode_times=False)
        try:
            # Most catchment models run on one layer: naming it 'recharge_layer1'
            # would suffix every variable of every file for nothing.
            assert ds["recharge"].dims == ("time", "n_face")
            assert "recharge_layer1" not in ds
        finally:
            ds.close()


@pytest.fixture
def catalog_on_lambert93(tmp_path):
    """A catalog whose mesh really sits in Lambert-93, with two contrasted fields.

    Reprojection only says something on coordinates that are valid in the source
    CRS, so this mesh covers a 1 km square of the Nancon catchment: a continuous
    field (head, in m) and a categorical one (seepage_mask, 0/1).
    """
    with simulation_catalog(tmp_path / "workspace") as c:
        sid = str(uuid4())
        reg = c.register_simulation(
            sid,
            project="test",
            solver="modflow6",
            n_cells=4,
            n_layers=1,
            n_timesteps=1,
            crs="EPSG:2154",
        )
        if reg.zarr is not None:
            reg.zarr.close()

        x0, y0, step = 385000.0, 6814000.0, 500.0
        verts = np.array(
            [[x0 + i * step, y0 + j * step] for j in range(3) for i in range(3)],
            dtype="float64",
        )
        conn = np.array(
            [[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]],
            dtype="int32",
        )
        c.write_mesh(sid, verts, conn, np.array([50.0, 0.0]))
        c.write_time(sid, np.array([0], dtype="int64"))
        c.write_crs(sid, crs_wkt="EPSG:2154", epsg_code=2154)
        c.write_field(sid, "head", 0, np.array([[12.5, 14.25, 16.75, 19.0]]), n_timesteps=1)
        c.write_field(
            sid,
            "seepage_mask",
            0,
            np.array([0.0, 1.0, 1.0, 0.0]),
            n_timesteps=1,
            subgroup="derived",
        )
        yield c, sid, tmp_path, (x0, y0, x0 + 2 * step, y0 + 2 * step)


def _lonlat_envelope(bounds: tuple[float, float, float, float]) -> tuple[float, ...]:
    """Lon/lat envelope of a Lambert-93 rectangle, corner by corner.

    Meridian convergence rotates the rectangle: the westernmost point is a
    different corner from the southernmost one, so the envelope is not
    the transform of (xmin, ymin) and (xmax, ymax).
    """
    from pyproj import Transformer

    xmin, ymin, xmax, ymax = bounds
    to_wgs84 = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)
    lons, lats = to_wgs84.transform([xmin, xmin, xmax, xmax], [ymin, ymax, ymin, ymax])
    return min(lons), min(lats), max(lons), max(lats)


class TestExportReprojection:
    """'crs' reprojects the export; it used to only relabel it."""

    def test_a_raster_without_a_crs_keeps_the_native_grid(self, catalog_on_lambert93):
        import rasterio

        catalog, sid, tmp_path, bounds = catalog_on_lambert93
        out = tmp_path / "native.tif"
        catalog.export(sid, ExportSpec(var="head", dest=out, time=0, resolution=100.0))

        with rasterio.open(str(out)) as src:
            assert src.crs.to_epsg() == 2154
            assert tuple(src.bounds) == pytest.approx(bounds)

    def test_a_raster_asked_for_another_crs_is_warped_not_relabelled(self, catalog_on_lambert93):
        import rasterio

        catalog, sid, tmp_path, bounds = catalog_on_lambert93
        out = tmp_path / "wgs84.tif"
        catalog.export(
            sid, ExportSpec(var="head", dest=out, time=0, resolution=100.0, crs="EPSG:4326")
        )

        lon_min, lat_min, lon_max, lat_max = _lonlat_envelope(bounds)
        with rasterio.open(str(out)) as src:
            assert src.crs.to_epsg() == 4326
            # A relabelled file would still carry metre bounds near 385000.
            assert src.bounds.left == pytest.approx(lon_min, abs=1e-3)
            assert src.bounds.right == pytest.approx(lon_max, abs=1e-3)
            assert src.bounds.bottom == pytest.approx(lat_min, abs=1e-3)
            assert src.bounds.top == pytest.approx(lat_max, abs=1e-3)
            assert src.res[0] < 1.0  # degrees, not metres
            valid = src.read(1)[src.read(1) != -9999.0]
            # Bilinear interpolates, it does not extrapolate: the warped field
            # stays inside the range of the four cell values.
            assert valid.min() == pytest.approx(12.5, abs=1e-9)
            assert valid.max() == pytest.approx(19.0, abs=1e-9)

    def test_a_categorical_raster_is_warped_without_inventing_classes(self, catalog_on_lambert93):
        import rasterio

        catalog, sid, tmp_path, _bounds = catalog_on_lambert93
        out = tmp_path / "mask_wgs84.tif"
        catalog.export(
            sid, ExportSpec(var="seepage_mask", dest=out, time=0, resolution=100.0, crs="EPSG:4326")
        )

        with rasterio.open(str(out)) as src:
            assert src.crs.to_epsg() == 4326
            data = src.read(1)
            assert set(np.unique(data[data != -9999.0])) <= {0.0, 1.0}

    def test_a_vector_asked_for_another_crs_is_reprojected(self, catalog_on_lambert93):
        import geopandas as gpd

        catalog, sid, tmp_path, bounds = catalog_on_lambert93
        out = tmp_path / "cells_wgs84.gpkg"
        catalog.export(sid, ExportSpec(var="head", dest=out, time=0, crs="EPSG:4326"))

        gdf = gpd.read_file(str(out))
        lon_min, lat_min, lon_max, lat_max = _lonlat_envelope(bounds)
        assert gdf.crs.to_epsg() == 4326
        assert len(gdf) == 4
        assert gdf.total_bounds == pytest.approx([lon_min, lat_min, lon_max, lat_max], abs=1e-9)

    def test_a_vector_without_a_crs_keeps_the_native_geometries(self, catalog_on_lambert93):
        import geopandas as gpd

        catalog, sid, tmp_path, bounds = catalog_on_lambert93
        out = tmp_path / "cells_native.gpkg"
        catalog.export(sid, ExportSpec(var="head", dest=out, time=0))

        gdf = gpd.read_file(str(out))
        assert gdf.crs.to_epsg() == 2154
        assert gdf.total_bounds == pytest.approx(bounds)

    def test_the_resampling_rule_splits_masks_from_continuous_fields(self):
        from rasterio.enums import Resampling

        from hydromodpy.results import field_registry
        from hydromodpy.results.exporters.geotiff import _resampling_for

        mask = field_registry.get("seepage_mask")
        head = field_registry.get("head")
        assert _resampling_for(mask, np.array([0.0, 1.0, 1.0])) is Resampling.nearest
        assert _resampling_for(head, np.array([12.5, 14.25])) is Resampling.bilinear
        # Dimensionless but fractional: a storage coefficient is not a class code.
        porosity = field_registry.get("porosity")
        assert _resampling_for(porosity, np.array([0.1, 0.25])) is Resampling.bilinear
        assert _resampling_for(head, np.array([np.nan, np.nan])) is Resampling.nearest
