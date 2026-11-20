"""CRS helpers of ``core.io``: the stamp on a producer's output, the frame of an overlay, grid selection.

``ensure_crs`` rewrites metadata and never pixels. ``to_mesh_crs`` brings a vector layer
into the frame of a mesh, which stores bare coordinates, so both frames are named by the
caller and a missing one is refused. Lengths are in m, forcing units are converted to mm, deg C and MJ/m2.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
import xarray as xr
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, box

from hydromodpy.catchment.algorithms.metric_crs import measure_polygon_area_m2
from hydromodpy.core.io import crs as crs_io
from hydromodpy.core.io.crs import measure_linework_length_m, project_gdf_for_metric_operations

_KM_LINE = LineString([(0.0, 0.0), (1000.0, 0.0)])

L93_PROJ4_WITHOUT_DATUM = (  # pyproj identifies it as EPSG:2154, yet finds it unequal to it
    "+proj=lcc +lat_0=46.5 +lon_0=3 +lat_1=49 +lat_2=44 +x_0=700000 +y_0=6600000 +ellps=GRS80 +units=m +no_defs"
)  # fmt: skip


def _write_tif_without_crs(path: Path) -> np.ndarray:
    values = np.arange(12, dtype="float32").reshape(3, 4)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=3,
        width=4,
        count=1,
        dtype="float32",
        transform=from_origin(0.0, 75.0, 25.0, 25.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(values, 1)
    return values


def test_missing_shapefile(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Shapefile not found"):
        crs_io.ensure_crs(tmp_path / "missing.shp", "EPSG:2154")


LAMBERT93 = "EPSG:2154"


def test_layer_in_the_mesh_frame() -> None:
    line = LineString([(-1.68, 48.11), (-1.67, 48.12)])

    (projected,) = crs_io.to_mesh_crs([line], mesh_crs=LAMBERT93, geometry_crs="EPSG:4326")

    to_lambert = Transformer.from_crs("EPSG:4326", LAMBERT93, always_xy=True)
    expected = np.column_stack(to_lambert.transform(*np.asarray(line.coords).T))
    np.testing.assert_allclose(np.asarray(projected.coords), expected)


@pytest.mark.parametrize("missing", ["mesh_crs", "geometry_crs"])
@pytest.mark.parametrize("value", [None, "", "   "], ids=["none", "empty", "blank"])
def test_missing_frame(missing: str, value: str | None) -> None:
    frames = {"mesh_crs": LAMBERT93, "geometry_crs": LAMBERT93, missing: value}

    with pytest.raises(ValueError, match=f"explicit {missing}"):
        crs_io.to_mesh_crs([Point(0.0, 0.0)], **frames)


@pytest.mark.parametrize(
    ("left", "right", "same"),
    [
        ("EPSG:2154", " epsg:2154", True),
        ("EPSG:4326", "WGS84", True),
        ("EPSG:2154", "EPSG:4326", False),
        ("EPSG:2154", "not a crs", False),
        (L93_PROJ4_WITHOUT_DATUM, "EPSG:2154", True),
        ("EPSG:4326", "OGC:CRS84", True),
    ],
    ids=["label", "parsed", "other", "unreadable", "proj4-identified-as-its-epsg", "axis-order"],
)
def test_same_crs(left: str, right: str, same: bool) -> None:
    assert crs_io.same_crs(left, right) is same


def test_centroid_in_lon_lat() -> None:
    layer = gpd.GeoDataFrame(
        geometry=[box(699_000, 6_599_000, 701_000, 6_601_000)], crs="EPSG:2154"
    )

    lon, lat = crs_io.get_centroid_coordinates(layer)

    assert (lon, lat) == pytest.approx(
        (2.9999, 46.5), abs=0.05
    )  # 700 km / 6600 km Lambert-93 is near 3 E, 46.5 N


@pytest.mark.parametrize("situation", ["none", "empty", "no crs"])
def test_no_centroid(situation: str) -> None:
    layer = {
        "none": None,
        "empty": gpd.GeoDataFrame(geometry=[], crs="EPSG:2154"),
        "no crs": gpd.GeoDataFrame(geometry=[Point(0, 0)]),
    }[situation]

    assert crs_io.get_centroid_coordinates(layer) == (None, None)


def test_dem_pixel_coordinates(tmp_path: Path) -> None:
    path = tmp_path / "dem.tif"
    _write_tif_without_crs(path)  # 3 rows x 4 columns, unit pixels from the origin

    coordinates = crs_io.transform_coordinates(str(path), "EPSG:2154", "EPSG:2154")

    assert len(coordinates) == 12
    assert coordinates[0] == pytest.approx((0.0, 75.0))  # top left corner of the raster
    assert coordinates[1][0] - coordinates[0][0] == pytest.approx(25.0)  # one pixel to the east


def test_unreadable_dem(tmp_path: Path) -> None:
    assert (
        crs_io.transform_coordinates(str(tmp_path / "absent.tif"), "EPSG:2154", "EPSG:4326") == []
    )


def test_coordinates_inside_shape(tmp_path: Path) -> None:
    shape = tmp_path / "basin.shp"
    gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10)], crs="EPSG:2154").to_file(shape)

    kept = crs_io.filter_coordinates_by_shape([(5, 5), (20, 20), (0, 5)], str(shape), "EPSG:2154")

    assert kept == [(5, 5), (0, 5)]  # the border counts as inside


def test_unreadable_shape(tmp_path: Path) -> None:
    assert (
        crs_io.filter_coordinates_by_shape([(1, 1)], str(tmp_path / "absent.shp"), "EPSG:2154")
        == []
    )


def _grid():
    return xr.Dataset(
        {"t": (("latitude", "longitude"), np.arange(12.0).reshape(3, 4))},
        coords={"longitude": [0.0, 1.0, 2.0, 3.0], "latitude": [10.0, 11.0, 12.0]},
    )


def test_nearest_grid_point() -> None:
    point = crs_io.select_nearest_point(_grid(), 1.2, 11.9)

    assert float(point.t) == 9.0  # latitude 12 is row 2, longitude 1 is column 1


@pytest.mark.parametrize(("lon", "lat"), [(None, 11.0), (1.0, None)])
def test_nearest_point_needs_both(lon, lat) -> None:
    assert crs_io.select_nearest_point(_grid(), lon, lat) is None


def test_points_within_polygon() -> None:
    polygon = gpd.GeoDataFrame(geometry=[box(0.5, 10.5, 2.5, 11.5)], crs="EPSG:4326")

    inside = crs_io.select_within_polygon_points(_grid(), polygon)

    assert inside.longitude.values.tolist() == [1.0, 2.0]
    assert inside.latitude.values.tolist() == [11.0]


def test_grid_kept_without_polygon() -> None:
    grid = _grid()

    assert crs_io.select_within_polygon_points(grid, None) is grid


@pytest.mark.parametrize(
    ("variable", "value", "expected"),
    [
        ("precipitation", 0.002, 2.0),  # m to mm
        ("temperature", 293.15, 20.0),  # K to degrees C
        ("radiation", 15_000_000.0, 15.0),  # J/m2 to MJ/m2
        ("humidity", 55.0, 55.0),  # unknown variable: unchanged
    ],
)
def test_convert_units(variable, value, expected) -> None:
    assert crs_io.convert_units(value, variable) == pytest.approx(expected)


def _frame(geometry, crs):
    return gpd.GeoDataFrame(geometry=[geometry], crs=crs)


@pytest.mark.parametrize(
    ("frame", "fallback", "crs"),
    [
        (_frame(_KM_LINE, None), "EPSG:2154", "EPSG:2154"),
        (_frame(_KM_LINE, "EPSG:4326"), "EPSG:2154", "EPSG:2154"),
        (_frame(_KM_LINE, "EPSG:2154"), None, "EPSG:2154"),
        (_frame(LineString([(-1.6, 48.1), (-1.6, 48.11)]), "EPSG:4326"), None, "EPSG:32630"),
        (_frame(_KM_LINE, None), None, None),
    ],
    ids=["no crs", "degrees label on metres", "projected", "degrees", "nothing to go on"],
)
def test_metric_crs(frame, fallback, crs) -> None:
    out = project_gdf_for_metric_operations(frame, fallback_crs=fallback)
    assert (None if out.crs is None else out.crs.to_string()) == crs
    if crs == "EPSG:32630":
        assert measure_linework_length_m(frame) == pytest.approx(1112.0, rel=0.01)


def test_empty_frame() -> None:
    empty = gpd.GeoDataFrame(geometry=[], crs="EPSG:2154")
    assert project_gdf_for_metric_operations(empty) is empty
    assert measure_linework_length_m(empty) == 0.0
    assert measure_polygon_area_m2(empty) == 0.0
    assert measure_polygon_area_m2(_frame(box(0, 0, 10, 10), "EPSG:2154")) == 100.0
