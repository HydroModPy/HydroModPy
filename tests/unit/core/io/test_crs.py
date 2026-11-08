"""The CRS helpers of ``core``: the stamp on a producer's output, and the frame of an overlay.

``ensure_crs`` stamps a producer's own output, and nothing else. The helper
moved here from ``spatial.geographic.geographic_io`` so that a terrain engine
can stamp what it writes without importing a sibling package. The raster
branch had no test before that move; it has one now, because the whole point
of the function is that it rewrites metadata and not pixels.

``to_mesh_crs`` brings a vector layer into the frame of a mesh before an
overlay. A mesh stores bare coordinates, so both frames are named by the
caller and a missing one is refused rather than guessed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from pyproj import CRS, Transformer
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


def test_the_shapefile_branch_writes_a_prj_without_reopening_the_vector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shp_path = tmp_path / "domain.shp"
    shp_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        crs_io.gpd,
        "read_file",
        lambda *_args, **_kwargs: pytest.fail("shapefile should not be reopened"),
    )

    crs_io.ensure_crs(shp_path, "EPSG:2154")

    expected_wkt = CRS.from_user_input("EPSG:2154").to_wkt(version="WKT1_ESRI")
    assert shp_path.with_suffix(".prj").read_text(encoding="utf-8") == expected_wkt


def test_a_missing_shapefile_is_named_in_the_refusal(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Shapefile not found"):
        crs_io.ensure_crs(tmp_path / "missing.shp", "EPSG:2154")


def test_the_raster_branch_declares_the_crs_and_leaves_the_band_alone(tmp_path: Path) -> None:
    tif_path = tmp_path / "accumulation.tif"
    values = _write_tif_without_crs(tif_path)
    with rasterio.open(tif_path) as src:
        assert src.crs is None
        before = hashlib.sha256(src.read(1).tobytes()).hexdigest()

    crs_io.ensure_crs(tif_path, "EPSG:2154")

    with rasterio.open(tif_path) as src:
        assert src.crs == rasterio.crs.CRS.from_user_input("EPSG:2154")
        assert hashlib.sha256(src.read(1).tobytes()).hexdigest() == before
        assert src.nodata == -9999.0
        np.testing.assert_array_equal(src.read(1), values)


def test_declaring_nothing_leaves_the_file_untouched(tmp_path: Path) -> None:
    """A caller with no CRS to declare is not a caller in error."""
    tif_path = tmp_path / "accumulation.tif"
    _write_tif_without_crs(tif_path)
    before = tif_path.read_bytes()

    crs_io.ensure_crs(tif_path, None)
    crs_io.ensure_crs(tmp_path / "missing.shp", None)

    assert tif_path.read_bytes() == before


# -- the frame of an overlay ---------------------------------------------------

LAMBERT93 = "EPSG:2154"


def test_a_layer_in_another_frame_comes_back_in_the_mesh_frame() -> None:
    line = LineString([(-1.68, 48.11), (-1.67, 48.12)])

    (projected,) = crs_io.to_mesh_crs([line], mesh_crs=LAMBERT93, geometry_crs="EPSG:4326")

    to_lambert = Transformer.from_crs("EPSG:4326", LAMBERT93, always_xy=True)
    expected = np.column_stack(to_lambert.transform(*np.asarray(line.coords).T))
    np.testing.assert_allclose(np.asarray(projected.coords), expected)


def test_a_layer_already_in_the_mesh_frame_comes_back_as_it_is() -> None:
    line = LineString([(350_000.0, 6_790_000.0), (350_100.0, 6_790_000.0)])

    parts = crs_io.to_mesh_crs([line], mesh_crs=LAMBERT93, geometry_crs=CRS.from_epsg(2154))

    assert len(parts) == 1
    assert parts[0] is line


def test_missing_and_empty_geometries_are_left_out() -> None:
    point = Point(350_000.0, 6_790_000.0)

    parts = crs_io.to_mesh_crs(
        [None, LineString(), point], mesh_crs=LAMBERT93, geometry_crs=LAMBERT93
    )
    nothing = crs_io.to_mesh_crs([None, LineString()], mesh_crs=LAMBERT93, geometry_crs="EPSG:4326")

    assert parts == [point]
    assert nothing == []


@pytest.mark.parametrize("missing", ["mesh_crs", "geometry_crs"])
@pytest.mark.parametrize("value", [None, "", "   "], ids=["none", "empty", "blank"])
def test_a_missing_frame_is_refused_by_name(missing: str, value: str | None) -> None:
    frames = {"mesh_crs": LAMBERT93, "geometry_crs": LAMBERT93, missing: value}

    with pytest.raises(ValueError, match=f"explicit {missing}"):
        crs_io.to_mesh_crs([Point(0.0, 0.0)], **frames)


@pytest.mark.parametrize(
    "crs_like", [2154, "EPSG:2154", CRS.from_epsg(2154)], ids=["int", "str", "crs"]
)
def test_a_crs_is_read_from_a_code_a_string_or_a_crs(crs_like: crs_io.CrsLike) -> None:
    assert crs_io.require_crs(crs_like, "mesh_crs") == CRS.from_epsg(2154)


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
def test_two_labels_name_the_same_frame_only_when_pyproj_agrees(
    left: str, right: str, same: bool
) -> None:
    assert crs_io.same_crs(left, right) is same


def test_a_raster_crs_reads_as_text_and_its_absence_as_none(tmp_path: Path) -> None:
    path = tmp_path / "bare.tif"
    _write_tif_without_crs(path)
    with rasterio.open(path) as src:
        assert crs_io.crs_text(src.crs) is None
    crs_io.ensure_crs(path, "EPSG:2154")
    with rasterio.open(path) as src:
        assert crs_io.crs_text(src.crs) == "EPSG:2154"


# ---- coordinate helpers -----------------------------------------------------


def test_a_wgs84_point_comes_back_in_the_utm_zone_that_holds_it() -> None:
    utm, easting, northing = crs_io.reproject_coord(3.0, 47.0)  # lon, lat

    assert utm == "EPSG:32631"
    assert easting == pytest.approx(500_000.0, abs=1.0)  # on the central meridian of zone 31
    assert northing == pytest.approx(5_207_000.0, abs=2_000.0)


def test_a_shapefile_is_rewritten_in_the_crs_asked(tmp_path: Path) -> None:
    import geopandas as gpd

    raw = tmp_path / "raw.shp"
    gpd.GeoDataFrame(geometry=[Point(700_000.0, 6_600_000.0)], crs="EPSG:2154").to_file(raw)

    crs_io.reproject_shp(str(raw), str(tmp_path / "out.shp"), "EPSG:2154")

    assert gpd.read_file(tmp_path / "out.shp").crs.to_epsg() == 2154


def test_the_centroid_of_a_layer_is_given_as_longitude_and_latitude() -> None:
    import geopandas as gpd
    from shapely.geometry import box

    layer = gpd.GeoDataFrame(
        geometry=[box(699_000, 6_599_000, 701_000, 6_601_000)], crs="EPSG:2154"
    )

    lon, lat = crs_io.get_centroid_coordinates(layer)

    assert (lon, lat) == pytest.approx(
        (2.9999, 46.5), abs=0.05
    )  # 700 km / 6600 km Lambert-93 is near 3 E, 46.5 N


@pytest.mark.parametrize("situation", ["none", "empty", "no crs"])
def test_a_layer_that_cannot_give_a_centroid_gives_none_none(situation: str) -> None:
    import geopandas as gpd

    layer = {
        "none": None,
        "empty": gpd.GeoDataFrame(geometry=[], crs="EPSG:2154"),
        "no crs": gpd.GeoDataFrame(geometry=[Point(0, 0)]),
    }[situation]

    assert crs_io.get_centroid_coordinates(layer) == (None, None)


def test_the_pixel_coordinates_of_a_dem_are_converted_cell_by_cell(tmp_path: Path) -> None:
    path = tmp_path / "dem.tif"
    _write_tif_without_crs(path)  # 3 rows x 4 columns, unit pixels from the origin

    coordinates = crs_io.transform_coordinates(str(path), "EPSG:2154", "EPSG:2154")

    assert len(coordinates) == 12
    assert coordinates[0] == pytest.approx((0.0, 75.0))  # top left corner of the raster
    assert coordinates[1][0] - coordinates[0][0] == pytest.approx(25.0)  # one pixel to the east


def test_a_dem_that_cannot_be_opened_gives_no_coordinates(tmp_path: Path) -> None:
    assert (
        crs_io.transform_coordinates(str(tmp_path / "absent.tif"), "EPSG:2154", "EPSG:4326") == []
    )


def test_only_the_coordinates_inside_the_shape_are_kept(tmp_path: Path) -> None:
    import geopandas as gpd
    from shapely.geometry import box

    shape = tmp_path / "basin.shp"
    gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10)], crs="EPSG:2154").to_file(shape)

    kept = crs_io.filter_coordinates_by_shape([(5, 5), (20, 20), (0, 5)], str(shape), "EPSG:2154")

    assert kept == [(5, 5), (0, 5)]  # the border counts as inside


def test_an_unreadable_shape_keeps_no_coordinate(tmp_path: Path) -> None:
    assert (
        crs_io.filter_coordinates_by_shape([(1, 1)], str(tmp_path / "absent.shp"), "EPSG:2154")
        == []
    )


def _grid():
    import xarray as xr

    return xr.Dataset(
        {"t": (("latitude", "longitude"), np.arange(12.0).reshape(3, 4))},
        coords={"longitude": [0.0, 1.0, 2.0, 3.0], "latitude": [10.0, 11.0, 12.0]},
    )


def test_the_nearest_grid_point_is_selected() -> None:
    point = crs_io.select_nearest_point(_grid(), 1.2, 11.9)

    assert float(point.t) == 9.0  # latitude 12 is row 2, longitude 1 is column 1


@pytest.mark.parametrize(("lon", "lat"), [(None, 11.0), (1.0, None)])
def test_without_both_coordinates_no_point_is_selected(lon, lat) -> None:
    assert crs_io.select_nearest_point(_grid(), lon, lat) is None


def test_points_outside_the_polygon_are_dropped_from_the_grid() -> None:
    import geopandas as gpd
    from shapely.geometry import box

    polygon = gpd.GeoDataFrame(geometry=[box(0.5, 10.5, 2.5, 11.5)], crs="EPSG:4326")

    inside = crs_io.select_within_polygon_points(_grid(), polygon)

    assert inside.longitude.values.tolist() == [1.0, 2.0]
    assert inside.latitude.values.tolist() == [11.0]


def test_a_grid_is_returned_whole_when_the_polygon_cannot_be_used() -> None:
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
def test_the_units_of_a_forcing_variable_are_converted(variable, value, expected) -> None:
    assert crs_io.convert_units(value, variable) == pytest.approx(expected)


def test_the_crs_of_a_label_written_in_wkt_is_recognised_as_the_epsg_one() -> None:
    assert crs_io.same_crs(CRS.from_epsg(2154).to_wkt(), "EPSG:2154")


def test_a_label_pyproj_cannot_read_matches_nothing_not_even_itself_altered() -> None:
    assert crs_io.same_crs("not a crs", "EPSG:2154") is False


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
def test_a_frame_is_put_in_one_metric_crs_before_it_is_measured(frame, fallback, crs) -> None:
    out = project_gdf_for_metric_operations(frame, fallback_crs=fallback)
    assert (None if out.crs is None else out.crs.to_string()) == crs
    if crs == "EPSG:32630":
        assert measure_linework_length_m(frame) == pytest.approx(1112.0, rel=0.01)


def test_an_empty_frame_measures_nothing() -> None:
    empty = gpd.GeoDataFrame(geometry=[], crs="EPSG:2154")
    assert project_gdf_for_metric_operations(empty) is empty
    assert measure_linework_length_m(empty) == 0.0
    assert measure_polygon_area_m2(empty) == 0.0
    assert measure_polygon_area_m2(_frame(box(0, 0, 10, 10), "EPSG:2154")) == 100.0
