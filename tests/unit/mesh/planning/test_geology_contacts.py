"""Geology contacts are the shared boundaries of zones, oriented with their zones.

A contact runs between two zones of different keys, with the zone whose key
sorts first on its left, whatever the order of the polygons. A vector map is
read in the project CRS, a raster has no contact, and the bands and rings of an
analytical support give theirs. A map or a support whose zones cannot give
contacts is refused with a message that names it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pytest
from shapely.affinity import translate
from shapely.geometry import LineString, Point, Polygon, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.mesh.planning.geology_contacts import (
    GeologyLines,
    contact_lines,
    geology_lines,
    support_contacts,
)
from hydromodpy.model.domain.spatial_support_config import (
    GeneratedBandsSupportConfig,
    GeneratedRingsSupportConfig,
)
from tests._helpers.mesh_cases import LAMBERT93_WKT

_L93 = LAMBERT93_WKT


def _serving(frame: gpd.GeoDataFrame) -> Callable[..., Mapping[str, Any]]:
    """A ``read_vector`` serving one map already read, so no test here opens the data layer."""

    def read_vector(config, config_path=None):
        return {"gdf": frame}

    return read_vector


def _refusing() -> Callable[..., Mapping[str, Any]]:
    """A ``read_vector`` a case that reads no vector map must never reach."""

    def read_vector(config, config_path=None):
        raise AssertionError("this geology_lines case reads no vector map")

    return read_vector


def _frame_from_file(path: Path, code_field: str = "code") -> gpd.GeoDataFrame:
    """Read one vector map from disk and name its zones the way the data reader does."""
    frame = gpd.read_file(path)
    frame["zone_key"] = frame[code_field].astype(str).str.strip()
    return frame


_T_MAP = (
    ("a", box(0.0, 0.0, 200.0, 100.0)),
    ("b", box(0.0, 100.0, 100.0, 200.0)),
    ("c", box(100.0, 100.0, 200.0, 200.0)),
)


@pytest.mark.parametrize(
    "source",
    [{"path": "geology.tif"}, {"path": "g.dat", "kind": "raster"}],
    ids=["by extension", "by kind"],
)
def test_raster_has_no_contacts(source: dict) -> None:
    contacts = geology_lines(
        {"source": source}, config_path=None, crs_wkt=_L93, read_vector=_refusing()
    )

    assert contacts is None


def test_vector_contacts(tmp_path) -> None:
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
        read_vector=_serving(_frame_from_file(path)),
    )
    pairs = {(left, right) for left, right in zip(contacts.zone_left, contacts.zone_right)}
    assert pairs == {("1", "3"), ("2", "3"), ("1", "2")}


def test_map_reprojected(tmp_path) -> None:
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
        read_vector=_serving(_frame_from_file(path)),
    )
    expected = contact_lines((str(code), polygon) for code, polygon in zones)
    assert len(contacts.lines) == len(expected.lines) == 3
    assert contacts.zone_left == expected.zone_left
    for got, want in zip(contacts.lines, expected.lines, strict=True):
        assert got.hausdorff_distance(want) < 1.0e-3


_BOUNDS = (0.0, 0.0, 200.0, 100.0)


def test_band_contacts() -> None:
    support = GeneratedBandsSupportConfig(
        kind="generated_bands",
        coordinate_mode="absolute",
        breaks=[50.0, 120.0],
        labels=["a", "b", "c"],
    )
    contacts = support_contacts(support, _BOUNDS)

    assert {(left, right) for left, right in zip(contacts.zone_left, contacts.zone_right)} == {
        ("a", "b"),
        ("b", "c"),
    }
    xs = sorted(line.coords[0][0] for line in contacts.lines)
    assert xs == [50.0, 120.0]
    for line, left in zip(contacts.lines, contacts.zone_left):
        west = {"a": 50.0, "b": 120.0}[left]
        assert line.coords[0][0] == west and line.length == 100.0


def test_relative_band_breaks() -> None:
    support = GeneratedBandsSupportConfig(
        kind="generated_bands", axis="y", breaks=[0.25], labels=["south", "north"]
    )
    (line,) = support_contacts(support, _BOUNDS).lines

    assert {y for _, y in line.coords} == {25.0}
    assert line.length == 200.0


def test_ring_contacts() -> None:
    support = GeneratedRingsSupportConfig(
        kind="generated_rings",
        coordinate_mode="absolute",
        radii=[20.0, 40.0],
        labels=["in", "mid", "out"],
    )
    contacts = support_contacts(support, (0.0, 0.0, 100.0, 100.0))

    assert {(left, right) for left, right in zip(contacts.zone_left, contacts.zone_right)} == {
        ("in", "mid"),
        ("mid", "out"),
    }
    centre = Point(50.0, 50.0)
    for line, (left, _) in zip(contacts.lines, zip(contacts.zone_left, contacts.zone_right)):
        radius = {"in": 20.0, "mid": 40.0}[left]
        assert line.is_closed
        assert centre.distance(line) == pytest.approx(radius, abs=1e-2)
        assert line.length == pytest.approx(2.0 * np.pi * radius, rel=1e-3)


def test_relative_ring_radii() -> None:
    support = GeneratedRingsSupportConfig(kind="generated_rings", radii=[0.5], labels=["in", "out"])
    (line,) = support_contacts(support, _BOUNDS).lines

    assert Point(100.0, 50.0).distance(line) == pytest.approx(25.0, abs=1e-2)


def test_support_without_zones() -> None:
    assert support_contacts(object(), _BOUNDS) is None


def test_map_without_polygon() -> None:
    contacts = contact_lines((("a", None), ("b", Polygon())))

    assert contacts == GeologyLines(lines=(), zone_left=(), zone_right=())


def test_nested_zones_no_contact() -> None:
    """Overlapping polygons share no boundary: no face can follow their contact."""
    contacts = contact_lines(
        (("a", box(0.0, 0.0, 300.0, 300.0)), ("b", box(100.0, 100.0, 200.0, 200.0)))
    )

    assert contacts.lines == ()


def _map_with_no_crs(tmp_path) -> GeologyLines | None:
    frame = gpd.GeoDataFrame({"code": [1, 2]}, geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)])
    path = tmp_path / "geology_nocrs.gpkg"
    frame.to_file(path)
    config = {"source": {"path": str(path), "kind": "vector", "code_field": "code"}}
    return geology_lines(
        config,
        config_path=tmp_path / "project.toml",
        crs_wkt=_L93,
        read_vector=_serving(_frame_from_file(path)),
    )


def _rings(**members: object) -> GeologyLines | None:
    support = GeneratedRingsSupportConfig(
        kind="generated_rings", coordinate_mode="absolute", labels=["in", "out"], **members
    )
    return support_contacts(support, _BOUNDS)


def _source_with_no_path(_tmp_path):
    return geology_lines({"source": {}}, config_path=None, crs_wkt=_L93, read_vector=_refusing())


def _zone_drawn_as_a_line(_tmp_path):
    return contact_lines((("a", LineString([(0, 0), (1, 0)])),))


def _band_break_outside_the_extent(_tmp_path):
    support = GeneratedBandsSupportConfig(
        kind="generated_bands", coordinate_mode="absolute", breaks=[250.0], labels=["a", "b"]
    )
    return support_contacts(support, _BOUNDS)


def _ring_centre_outside_the_domain(_tmp_path):
    return _rings(radii=[10.0], center_x=250.0, center_y=50.0)


def _ring_wider_than_the_domain(_tmp_path):
    return _rings(radii=[60.0])


_REFUSALS = {
    "source with no path": (_source_with_no_path, "a geology support needs source.path"),
    "zone drawn as a line": (_zone_drawn_as_a_line, "geology zone 'a' holds a LineString"),
    "map with no CRS": (_map_with_no_crs, "declares no CRS"),
    "band break outside the extent": (
        _band_break_outside_the_extent,
        r"breaks of the generated_bands support lie outside \(0.0, 200.0\)",
    ),
    "ring centre outside the domain": (
        _ring_centre_outside_the_domain,
        "the centre of the generated_rings support lies outside its domain",
    ),
    "ring wider than the domain": (
        _ring_wider_than_the_domain,
        "must lie inside the largest circle around its centre",
    ),
}


@pytest.mark.filterwarnings("ignore:'crs' was not provided")
@pytest.mark.parametrize("case", list(_REFUSALS))
def test_refusals(case: str, tmp_path) -> None:
    build, message = _REFUSALS[case]

    with pytest.raises(MeshRequestError, match=message):
        build(tmp_path)
