from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, box

from hydromodpy.backends import get_whitebox_backend
from hydromodpy.backends.whitebox_tools_backend import _get_cached_whitebox_backend


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


def test_get_whitebox_backend_defaults_to_workflows(monkeypatch) -> None:
    monkeypatch.delenv("HYDROMODPY_WHITEBOX_BACKEND", raising=False)
    _get_cached_whitebox_backend.cache_clear()
    backend = get_whitebox_backend()
    assert backend.__class__.__name__ == "WhiteboxWorkflowsBackend"


def test_get_whitebox_backend_supports_workflows_selection(monkeypatch) -> None:
    monkeypatch.setenv("HYDROMODPY_WHITEBOX_BACKEND", "whitebox_workflows")
    _get_cached_whitebox_backend.cache_clear()
    backend = get_whitebox_backend()
    assert backend.__class__.__name__ == "WhiteboxWorkflowsBackend"


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
    eff = tmp_path / "eff.tif"
    absr = tmp_path / "abs.tif"

    backend.fill_depressions(str(dem), str(dem_fill))
    backend.breach_depressions(str(dem), str(dem_breach))
    backend.d8_pointer(str(dem_fill), str(direc))
    backend.d8_flow_accumulation(str(dem_fill), str(acc), log=True)
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
    ):
        assert path.exists()

    watershed_cols = set(gpd.read_file(watershed_shp).columns)
    assert "AREA" in watershed_cols

    point_cols = set(gpd.read_file(points_clip).columns)
    assert {"XCOORD", "YCOORD", "VALUE1"}.issubset(point_cols)
