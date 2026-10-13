"""Geology contacts are the shared boundaries of zones, oriented with their zones."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from pyproj import CRS
from shapely.affinity import translate
from shapely.geometry import LineString, Point, Polygon, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.planning.geology import contact_lines, geology_lines

_L93 = CRS.from_epsg(2154).to_wkt()
_T_MAP = (
    ("a", box(0.0, 0.0, 200.0, 100.0)),
    ("b", box(0.0, 100.0, 100.0, 200.0)),
    ("c", box(100.0, 100.0, 200.0, 200.0)),
)
_X_MAP = (
    ("a", box(0.0, 0.0, 100.0, 100.0)),
    ("b", box(100.0, 0.0, 200.0, 100.0)),
    ("c", box(0.0, 100.0, 100.0, 200.0)),
    ("d", box(100.0, 100.0, 200.0, 200.0)),
)


def _zone_on_side(line: LineString, zones: dict[str, Polygon], side: float) -> str:
    """The zone a point just beside the first segment of *line* falls in."""
    (x0, y0), (x1, y1) = line.coords[0], line.coords[1]
    length = np.hypot(x1 - x0, y1 - y0)
    probe = Point(
        0.5 * (x0 + x1) - side * (y1 - y0) / length, 0.5 * (y0 + y1) + side * (x1 - x0) / length
    )
    return next(key for key, polygon in zones.items() if polygon.contains(probe))


def _as_rows(contacts) -> list[tuple[str, str, tuple]]:
    return [
        (left, right, tuple(line.coords))
        for line, left, right in zip(
            contacts.lines, contacts.zone_left, contacts.zone_right, strict=True
        )
    ]


def test_a_t_junction_gives_three_contacts_with_their_zones() -> None:
    contacts = contact_lines(_T_MAP)
    zones = dict(_T_MAP)
    pairs = {(left, right) for left, right in zip(contacts.zone_left, contacts.zone_right)}
    assert pairs == {("a", "b"), ("a", "c"), ("b", "c")}
    assert sum(line.length for line in contacts.lines) == 300.0
    for line, left, right in zip(contacts.lines, contacts.zone_left, contacts.zone_right):
        assert _zone_on_side(line, zones, +1.0) == left
        assert _zone_on_side(line, zones, -1.0) == right
        assert Point(100.0, 100.0).distance(line) == 0.0


def test_an_x_junction_has_no_contact_across_the_corner() -> None:
    contacts = contact_lines(_X_MAP)
    pairs = {(left, right) for left, right in zip(contacts.zone_left, contacts.zone_right)}
    assert pairs == {("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")}
    assert all(line.length == 100.0 for line in contacts.lines)


def test_the_contacts_do_not_depend_on_the_polygon_order() -> None:
    reference = _as_rows(contact_lines(_X_MAP))
    shuffled = (_X_MAP[3], _X_MAP[1], _X_MAP[0], _X_MAP[2])
    assert _as_rows(contact_lines(shuffled)) == reference


def test_two_polygons_of_one_zone_share_no_contact() -> None:
    contacts = contact_lines(
        (
            ("a", box(0.0, 0.0, 1.0, 1.0)),
            ("a", box(1.0, 0.0, 2.0, 1.0)),
            ("b", box(0.0, 1.0, 2.0, 2.0)),
        )
    )
    assert contacts.zone_left == ("a",) and contacts.zone_right == ("b",)
    assert contacts.lines[0].length == 2.0


def test_an_island_zone_gives_a_closed_contact() -> None:
    outer = box(0.0, 0.0, 300.0, 300.0).difference(box(100.0, 100.0, 200.0, 200.0))
    contacts = contact_lines((("z", box(100.0, 100.0, 200.0, 200.0)), ("y", outer)))
    assert len(contacts.lines) == 1
    assert contacts.lines[0].is_closed
    assert (contacts.zone_left[0], contacts.zone_right[0]) == ("y", "z")
    assert contacts.lines[0].coords[0] == min(contacts.lines[0].coords)


def test_a_raster_source_has_no_contact_line() -> None:
    assert (
        geology_lines({"source": {"path": "geology.tif"}}, config_path=None, crs_wkt=_L93) is None
    )
    assert (
        geology_lines(
            {"source": {"path": "g.dat", "kind": "raster"}}, config_path=None, crs_wkt=_L93
        )
        is None
    )


def test_a_vector_source_reads_its_contacts(tmp_path) -> None:
    frame = gpd.GeoDataFrame(
        {"code": [3, 1, 2]},
        geometry=[polygon for _, polygon in _T_MAP],
        crs="EPSG:2154",
    )
    path = tmp_path / "geology.gpkg"
    frame.to_file(path)
    contacts = geology_lines(
        {"source": {"path": str(path), "kind": "vector", "code_field": "code"}},
        config_path=tmp_path / "project.toml",
        crs_wkt=_L93,
    )
    pairs = {(left, right) for left, right in zip(contacts.zone_left, contacts.zone_right)}
    assert pairs == {("1", "3"), ("2", "3"), ("1", "2")}


def test_a_map_in_another_crs_is_reprojected_to_the_project_crs(tmp_path) -> None:
    zones = [
        (code, translate(polygon, 350000.0, 6790000.0))
        for code, (_, polygon) in zip((3, 1, 2), _T_MAP)
    ]
    in_wgs84 = gpd.GeoSeries([polygon for _, polygon in zones], crs="EPSG:2154").to_crs(4326)
    frame = gpd.GeoDataFrame({"code": [3, 1, 2]}, geometry=list(in_wgs84), crs="EPSG:4326")
    path = tmp_path / "geology_wgs84.gpkg"
    frame.to_file(path)
    contacts = geology_lines(
        {"source": {"path": str(path), "kind": "vector", "code_field": "code"}},
        config_path=tmp_path / "project.toml",
        crs_wkt=_L93,
    )
    expected = contact_lines((str(code), polygon) for code, polygon in zones)
    assert len(contacts.lines) == len(expected.lines) == 3
    assert contacts.zone_left == expected.zone_left
    for got, want in zip(contacts.lines, expected.lines, strict=True):
        assert got.hausdorff_distance(want) < 1.0e-3


def test_a_map_with_no_crs_is_refused(tmp_path) -> None:
    frame = gpd.GeoDataFrame({"code": [1, 2]}, geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)])
    path = tmp_path / "geology_nocrs.gpkg"
    frame.to_file(path)
    config = {"source": {"path": str(path), "kind": "vector", "code_field": "code"}}
    with pytest.raises(MeshRequestError, match="no CRS"):
        geology_lines(config, config_path=tmp_path / "project.toml", crs_wkt=_L93)
