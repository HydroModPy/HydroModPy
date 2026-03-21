from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, box

import hydromodpy.backends as backends_pkg
from hydromodpy.backends import get_whitebox_backend
from hydromodpy.backends.whitebox_workflows_backend import (
    WhiteboxWorkflowsBackend,
    _get_cached_whitebox_backend,
)


def _write_raster(path: Path, data: np.ndarray, *, nodata: float = -9999.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "height": int(data.shape[0]),
        "width": int(data.shape[1]),
        "count": 1,
        "dtype": data.dtype,
        "crs": "EPSG:2154",
        "transform": from_origin(0.0, float(data.shape[0]), 1.0, 1.0),
        "nodata": nodata,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


def _count_active_cells(path: Path) -> int:
    with rasterio.open(path) as src:
        arr = np.asarray(src.read(1))
        nodata = src.nodata
    valid = np.isfinite(arr)
    if nodata is not None:
        valid &= arr != nodata
    return int(np.count_nonzero((arr > 0) & valid))


def test_get_whitebox_backend_defaults_to_workflows() -> None:
    _get_cached_whitebox_backend.cache_clear()
    backend = get_whitebox_backend()
    assert backend.__class__.__name__ == "WhiteboxWorkflowsBackend"


def test_get_whitebox_backend_supports_workflows_selection() -> None:
    _get_cached_whitebox_backend.cache_clear()
    backend = get_whitebox_backend("whitebox_workflows")
    assert backend.__class__.__name__ == "WhiteboxWorkflowsBackend"


def test_get_whitebox_backend_rejects_legacy_whitebox_selection() -> None:
    _get_cached_whitebox_backend.cache_clear()
    try:
        get_whitebox_backend("whitebox")
    except ValueError as exc:
        assert "only 'whitebox_workflows'" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("legacy whitebox backend selection should be rejected")


def test_package_no_longer_exposes_whitebox_tools_alias() -> None:
    try:
        backends_pkg.WhiteboxToolsBackend
    except AttributeError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("WhiteboxToolsBackend alias should no longer be exposed")


def test_whitebox_workflows_backend_suppresses_native_stdio(capfd) -> None:
    backend = WhiteboxWorkflowsBackend()

    def _noisy_native_operation():
        os.write(1, b"native-stdout\n")
        os.write(2, b"native-stderr\n")
        print("python-stdout")
        return 123

    assert backend._run_env_operation(_noisy_native_operation) == 123
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_whitebox_tools_backend_module_is_no_longer_importable() -> None:
    sys.modules.pop("hydromodpy.backends.whitebox_tools_backend", None)
    try:
        importlib.import_module("hydromodpy.backends.whitebox_tools_backend")
    except ModuleNotFoundError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("legacy whitebox_tools_backend module should be removed")


def test_whitebox_workflows_backend_smoke_operations(tmp_path: Path) -> None:
    backend = get_whitebox_backend("whitebox_workflows")

    dem = tmp_path / "dem.tif"
    polygon = tmp_path / "polygon.shp"
    points = tmp_path / "points.shp"
    lines = tmp_path / "lines.shp"

    _write_raster(
        dem,
        np.array(
            [
                [10.0, 9.0, 8.0, 7.0],
                [11.0, 10.0, 9.0, 8.0],
                [12.0, 11.0, 10.0, 9.0],
                [13.0, 12.0, 11.0, 10.0],
            ],
            dtype=np.float32,
        ),
    )
    gpd.GeoDataFrame({"id": [1]}, geometry=[box(0.0, 0.0, 3.0, 4.0)], crs="EPSG:2154").to_file(
        polygon
    )
    gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[Point(1.5, 2.5)],
        crs="EPSG:2154",
    ).to_file(points)
    gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[LineString([(0.5, 3.5), (2.5, 0.5)])],
        crs="EPSG:2154",
    ).to_file(lines)

    dem_fill = tmp_path / "dem_fill.tif"
    dem_breach = tmp_path / "dem_breach.tif"
    direc = tmp_path / "dem_direc.tif"
    acc = tmp_path / "dem_acc.tif"
    acc_cells = tmp_path / "dem_acc_cells.tif"
    clipped = tmp_path / "dem_clip.tif"
    points_clip = tmp_path / "points_clip.shp"
    snap_pts = tmp_path / "points_snap.shp"
    watershed_tif = tmp_path / "watershed.tif"
    watershed_shp = tmp_path / "watershed.shp"
    watershed_lines = tmp_path / "watershed_lines.shp"
    point_raster = tmp_path / "points.tif"
    line_raster = tmp_path / "lines.tif"
    poly_raster = tmp_path / "poly.tif"
    line_raster_nodata = tmp_path / "lines_nodata.tif"
    trace_raster = tmp_path / "trace.tif"
    downslope = tmp_path / "downslope.tif"
    mass_flux = tmp_path / "mass_flux.tif"
    streams = tmp_path / "streams.tif"
    streams_pruned = tmp_path / "streams_pruned.tif"
    streams_vector = tmp_path / "streams.shp"
    streams_order = tmp_path / "streams_order.tif"
    streams_link_id = tmp_path / "streams_link_id.tif"
    eff = tmp_path / "eff.tif"
    absr = tmp_path / "abs.tif"

    backend.fill_depressions(str(dem), str(dem_fill))
    backend.breach_depressions(str(dem), str(dem_breach))
    backend.d8_pointer(str(dem_fill), str(direc))
    backend.d8_flow_accumulation(str(dem_fill), str(acc), log=True)
    backend.d8_flow_accumulation(str(dem_fill), str(acc_cells), log=False)
    backend.extract_streams(str(acc_cells), str(streams), threshold=1, zero_background=True)
    backend.remove_short_streams(
        str(direc),
        str(streams),
        str(streams_pruned),
        min_length=0,
    )
    backend.strahler_stream_order(
        str(direc),
        str(streams_pruned),
        str(streams_order),
        zero_background=True,
    )
    backend.stream_link_identifier(
        str(direc),
        str(streams_pruned),
        str(streams_link_id),
        zero_background=True,
    )
    backend.raster_streams_to_vector(
        str(streams_pruned),
        str(direc),
        str(streams_vector),
        all_vertices=False,
    )
    backend.clip_raster_to_polygon(str(dem_fill), str(polygon), str(clipped), maintain_dimensions=False)
    backend.clip(str(points), str(polygon), str(points_clip))
    backend.snap_pour_points(str(points), str(acc), str(snap_pts), 2)
    backend.watershed(str(direc), str(snap_pts), str(watershed_tif))
    backend.raster_to_vector_polygons(str(watershed_tif), str(watershed_shp))
    backend.polygons_to_lines(str(watershed_shp), str(watershed_lines))
    backend.vector_points_to_raster(str(points), str(point_raster), field="id", base=str(dem_fill))
    backend.vector_lines_to_raster(str(lines), str(line_raster), field="id", base=str(dem_fill))
    backend.vector_polygons_to_raster(str(polygon), str(poly_raster), field="id", base=str(dem_fill))
    backend.set_nodata_value(str(line_raster), str(line_raster_nodata), back_value=-32768)
    backend.polygon_area(str(watershed_shp))
    backend.raster_to_vector_points(str(point_raster), str(tmp_path / "point_pixels.shp"))
    backend.trace_downslope_flowpaths(str(points), str(direc), str(trace_raster))
    backend.downslope_distance_to_stream(str(dem_fill), str(point_raster), str(downslope))
    backend.add_point_coordinates_to_table(str(points_clip))
    backend.extract_raster_values_at_points(str(point_raster), str(points_clip))

    _write_raster(eff, np.ones((4, 4), dtype=np.float32))
    _write_raster(absr, np.zeros((4, 4), dtype=np.float32))
    backend.d8_mass_flux(
        str(dem_fill),
        str(point_raster),
        str(eff),
        str(absr),
        str(mass_flux),
    )

    for path in (
        dem_fill,
        dem_breach,
        direc,
        acc,
        acc_cells,
        clipped,
        points_clip,
        snap_pts,
        watershed_tif,
        watershed_shp,
        watershed_lines,
        point_raster,
        line_raster,
        poly_raster,
        line_raster_nodata,
        trace_raster,
        downslope,
        mass_flux,
        streams,
        streams_pruned,
        streams_vector,
        streams_order,
        streams_link_id,
    ):
        assert path.exists()

    watershed_cols = set(gpd.read_file(watershed_shp).columns)
    assert "AREA" in watershed_cols

    point_cols = set(gpd.read_file(points_clip).columns)
    assert {"XCOORD", "YCOORD", "VALUE1"}.issubset(point_cols)

    stream_count = _count_active_cells(streams)
    stream_pruned_count = _count_active_cells(streams_pruned)
    stream_order_count = _count_active_cells(streams_order)
    stream_link_count = _count_active_cells(streams_link_id)

    assert stream_count > 0
    assert stream_pruned_count > 0
    assert stream_pruned_count <= stream_count
    assert stream_order_count > 0
    assert stream_link_count > 0
    assert not gpd.read_file(streams_vector).empty


def test_whitebox_workflows_backend_in_memory_chain(tmp_path: Path) -> None:
    backend = get_whitebox_backend()
    dem = tmp_path / "dem.tif"
    polygon = tmp_path / "polygon.shp"
    points = tmp_path / "points.shp"

    _write_raster(
        dem,
        np.array(
            [
                [10.0, 9.0, 8.0, 7.0],
                [11.0, 10.0, 9.0, 8.0],
                [12.0, 11.0, 10.0, 9.0],
                [13.0, 12.0, 11.0, 10.0],
            ],
            dtype=np.float32,
        ),
    )
    gpd.GeoDataFrame({"id": [1]}, geometry=[box(0.0, 0.0, 3.0, 4.0)], crs="EPSG:2154").to_file(
        polygon
    )
    gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[Point(1.5, 2.5)],
        crs="EPSG:2154",
    ).to_file(points)

    dem_data = backend.read_raster(str(dem))
    polygon_data = backend.read_vector(str(polygon))
    points_data = backend.read_vector(str(points))

    dem_fill = backend.fill_depressions_raster(dem_data)
    direc = backend.d8_pointer_raster(dem_fill)
    acc = backend.d8_flow_accumulation_raster(dem_fill, log=True)
    points_snap = backend.snap_pour_points_vector(points_data, acc, 2)
    watershed = backend.watershed_raster(direc, points_snap)
    watershed_poly = backend.raster_to_vector_polygons_raster(watershed)
    clipped = backend.clip_raster_to_polygon_raster(dem_fill, polygon_data, maintain_dimensions=False)

    backend.write_raster(clipped, str(tmp_path / "clipped.tif"))
    backend.write_vector(watershed_poly, str(tmp_path / "watershed_mem.shp"))

    assert (tmp_path / "clipped.tif").exists()
    assert (tmp_path / "watershed_mem.shp").exists()


def test_whitebox_workflows_backend_rejects_empty_vector_write(tmp_path: Path) -> None:
    backend = WhiteboxWorkflowsBackend()

    class _EmptyVector:
        records = []

    out_path = tmp_path / "empty.shp"

    with pytest.raises(ValueError, match="empty vector layer"):
        backend.write_vector(_EmptyVector(), str(out_path))
