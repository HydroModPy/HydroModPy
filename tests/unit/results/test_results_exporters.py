"""Format-level behavior of the exporters, reached through ``export_run``.

Each test writes one request to an exact ``file`` under the exports of the run:
the format follows its extension. The run is written by its store, sealed and
indexed; a test that adds data writes it the same way. What a request writes
by default, by kind and by date, is pinned in
``tests/unit/results/test_an_export_request_writes_what_it_names.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from pydantic import ValidationError

from hydromodpy.core.exceptions import ExportError
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.exporters.export_spec import ExportRequest
from hydromodpy.results.exporters.request import export_run
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store


class _Run:
    """The run of a test: written through its store, sealed and indexed at its first export.

    A test may add data before it exports; the run is sealed once, as a run is.
    """

    def __init__(self, project: Path, store: RunStore) -> None:
        self.project = project
        self.exports = store.run_dir / "exports"
        self._store: RunStore | None = store

    def write_field(self, sid: str, *args: Any, **kwargs: Any) -> None:
        self._open().write_field(sid, *args, **kwargs)

    def write_timeseries(self, sid: str, *args: Any, **kwargs: Any) -> None:
        self._open().write_timeseries(sid, *args, **kwargs)

    def write_crs(self, sid: str, *args: Any, **kwargs: Any) -> None:
        self._open().write_crs(sid, *args, **kwargs)

    def _open(self) -> RunStore:
        if self._store is None:
            raise AssertionError("the run is sealed: write before the first export")
        return self._store

    def export(self, sid: str, request: ExportRequest) -> list[Path]:
        if self._store is not None:
            seal_completed(self._store)
            rebuild_index(self.project)
            self._store = None
        with Catalog(self.project) as catalog:
            return export_run(catalog, sid, request)


def _export(run: _Run, sid: str, **request: Any) -> Path:
    """Write one request that names its file under the exports and return that file."""
    if isinstance(request.get("file"), Path):
        request["file"] = request["file"].relative_to(run.exports)
    (written,) = run.export(sid, ExportRequest(**request))
    return written


@pytest.fixture
def catalog_with_data(tmp_path):
    """A catalog with one simulation containing mesh, head field, and timeseries."""
    project = tmp_path / "workspace"
    n_cells, n_layers, n_ts = 6, 2, 3
    c = open_run_store(
        project,
        "demo",
        n_cells=n_cells,
        n_layers=n_layers,
        n_timesteps=n_ts,
        solver="modflow_nwt",
        crs_epsg=2154,
        crs_wkt="EPSG:2154",
    )
    sid = c.sim_id

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
    run = _Run(project, c)
    yield run, sid, run.exports


class TestNetCDFExport:
    def test_a_file_for_qgis_names_one_layer(self, catalog_with_data):
        # MDAL, what QGIS reads a mesh with, binds a dataset to the face
        # dimension and ignores an array carrying a third one.
        catalog, sid, exports = catalog_with_data
        out = exports / "one.nc"
        _export(catalog, sid, variables="head", file=out, layer=1)
        ds = xr.open_dataset(out, decode_times=False)
        assert ds["head"].dims == ("time", "n_face")
        assert int(ds["layer"]) == 1
        whole = exports / "whole.nc"
        _export(catalog, sid, variables="head", file=whole)
        with xr.open_dataset(whole, decode_times=False) as every:
            np.testing.assert_array_equal(ds["head"].values, every["head"].sel(layer=1).values)
        ds.close()


class TestGeoTIFFExport:
    def test_a_nodata_value_is_written_in_the_file(self, catalog_with_data):
        catalog, sid, exports = catalog_with_data
        out = exports / "nodata.tif"
        _export(catalog, sid, variables="head", file=out, time=0, layer=0, nodata=-1.0)
        import rasterio

        with rasterio.open(str(out)) as src:
            assert src.nodata == -1.0

    def test_a_resolution_left_out_follows_the_mesh(self, catalog_with_data):
        catalog, sid, exports = catalog_with_data
        out = exports / "auto.tif"
        assert _export(catalog, sid, variables="head", file=out, time=0, layer=0).exists()

    def test_a_field_of_several_layers_needs_a_layer(self, catalog_with_data):
        catalog, sid, exports = catalog_with_data
        with pytest.raises(ValueError, match="holds 2 layers and a GeoTIFF holds one"):
            _export(catalog, sid, variables="head", file=exports / "top.tif", time=0)


class TestShapefileExport:
    @pytest.mark.parametrize("suffix", [".shp", ".gpkg"])
    def test_a_field_of_several_layers_needs_a_layer(self, catalog_with_data, suffix):
        catalog, sid, exports = catalog_with_data
        with pytest.raises(ValueError, match="Write layer = 0"):
            _export(catalog, sid, variables="head", file=exports / f"cells{suffix}", time=0)


class TestExportErrors:
    def test_unknown_format(self, catalog_with_data):
        _catalog, _sid, exports = catalog_with_data
        # An unknown format is rejected at request construction, before any I/O.
        with pytest.raises(ValidationError):
            ExportRequest(variables="head", format="parquet", file=exports / "out.pq")

    def test_a_name_no_run_holds_is_refused(self, catalog_with_data):
        catalog, sid, exports = catalog_with_data
        with pytest.raises(ExportError, match="no run can export 'nonexistent_field'"):
            _export(catalog, sid, variables="nonexistent_field", file=exports / "missing.nc")


class TestNetCDFForQgis:
    """What MDAL, the driver QGIS reads a mesh with, needs to find in the file."""

    def test_crs_is_restated_the_way_mdal_reads_it(self, catalog_with_data):
        from pyproj import CRS

        catalog, sid, exports = catalog_with_data
        catalog.write_crs(sid, crs_wkt=CRS.from_epsg(2154).to_wkt(), epsg_code=2154)

        out = exports / "crs.nc"
        _export(catalog, sid, variables="head", file=out)

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

    def test_a_failed_export_leaves_the_previous_file_alone(self, catalog_with_data, monkeypatch):
        catalog, sid, exports = catalog_with_data
        out = exports / "kept.nc"
        _export(catalog, sid, variables="head", file=out)
        before = out.read_bytes()

        def fail_midway(self, path, *args, **kwargs):
            Path(path).write_bytes(b"half a file")
            raise OSError("no space left on device")

        monkeypatch.setattr(xr.Dataset, "to_netcdf", fail_midway)
        with pytest.raises(OSError):
            _export(catalog, sid, variables="head", file=out)

        assert out.read_bytes() == before
        assert not (exports / "kept.nc.tmp").exists()


@pytest.fixture
def catalog_on_lambert93(tmp_path):
    """A catalog whose mesh really sits in Lambert-93, with two contrasted fields.

    Reprojection only says something on coordinates that are valid in the source
    CRS, so this mesh covers a 1 km square of the Nancon catchment: a continuous
    field (head, in m) and a categorical one (seepage_mask, 0/1).
    """
    project = tmp_path / "workspace"
    c = open_run_store(
        project, "demo", n_cells=4, n_layers=1, n_timesteps=1, crs_epsg=2154, crs_wkt="EPSG:2154"
    )
    sid = c.sim_id

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
    run = _Run(project, c)
    yield run, sid, run.exports, (x0, y0, x0 + 2 * step, y0 + 2 * step)


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

        catalog, sid, exports, bounds = catalog_on_lambert93
        out = exports / "native.tif"
        _export(catalog, sid, variables="head", file=out, time=0, resolution=100.0)

        with rasterio.open(str(out)) as src:
            assert src.crs.to_epsg() == 2154
            assert tuple(src.bounds) == pytest.approx(bounds)

    def test_a_raster_asked_for_another_crs_is_warped_not_relabelled(self, catalog_on_lambert93):
        import rasterio

        catalog, sid, exports, bounds = catalog_on_lambert93
        out = exports / "wgs84.tif"
        _export(catalog, sid, variables="head", file=out, time=0, resolution=100.0, crs="EPSG:4326")

        lon_min, lat_min, lon_max, lat_max = _lonlat_envelope(bounds)
        with rasterio.open(str(out)) as src:
            assert src.crs.to_epsg() == 4326
            # A relabelled file would still carry meter bounds near 385000.
            assert src.bounds.left == pytest.approx(lon_min, abs=1e-3)
            assert src.bounds.right == pytest.approx(lon_max, abs=1e-3)
            assert src.bounds.bottom == pytest.approx(lat_min, abs=1e-3)
            assert src.bounds.top == pytest.approx(lat_max, abs=1e-3)
            assert src.res[0] < 1.0  # degrees, not meters
            valid = src.read(1)[src.read(1) != -9999.0]
            # Bilinear interpolates, it does not extrapolate: the warped field
            # stays inside the range of the four cell values.
            assert valid.min() == pytest.approx(12.5, abs=1e-9)
            assert valid.max() == pytest.approx(19.0, abs=1e-9)

    def test_a_vector_asked_for_another_crs_is_reprojected(self, catalog_on_lambert93):
        import geopandas as gpd

        catalog, sid, exports, bounds = catalog_on_lambert93
        out = exports / "cells_wgs84.gpkg"
        _export(catalog, sid, variables="head", file=out, time=0, crs="EPSG:4326")

        gdf = gpd.read_file(str(out))
        lon_min, lat_min, lon_max, lat_max = _lonlat_envelope(bounds)
        assert gdf.crs.to_epsg() == 4326
        assert len(gdf) == 4
        assert gdf.total_bounds == pytest.approx([lon_min, lat_min, lon_max, lat_max], abs=1e-9)

    def test_a_vector_without_a_crs_keeps_the_native_geometries(self, catalog_on_lambert93):
        import geopandas as gpd

        catalog, sid, exports, bounds = catalog_on_lambert93
        out = exports / "cells_native.gpkg"
        _export(catalog, sid, variables="head", file=out, time=0)

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
