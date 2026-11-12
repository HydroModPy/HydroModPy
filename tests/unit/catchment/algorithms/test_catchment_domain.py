"""A buffer of N per cent makes the modeled catchment N per cent larger in area.

Abherve et al. (2023, HESS 27, p. 3224) enlarge "the modeled domain by 10 %". The v1 code read the
same "10" as 10 per cent of sqrt(area in km2) km, +53 per cent of area on the Nancon (64.7 km2).
"N%" now solves that distance on the real polygon, and a bare number keeps the v1 rule with a
warning, so a sealed run replays its domain.
"""

import logging
import math
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pytest
from pydantic import ValidationError
from shapely.geometry import MultiPolygon, Point, Polygon, box

from hydromodpy.catchment.algorithms.catchment_domain import (
    CatchmentDomainProducts,
    buffer_area_increase,
    buffer_distance_for_area_increase,
    buffer_distance_m,
    compute_catchment_area_km2,
    derive_catchment_domain,
)
from hydromodpy.catchment.preprocess.catchment_delineation import CatchmentDelineation
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.core.exceptions import TerrainProductError
from tests._helpers.geographic_cases import write_features
from tests._helpers.geotiffs import write_geotiff

NANCON_AREA_M2 = 64.7e6
SIDE = math.sqrt(NANCON_AREA_M2)
SQUARE_SOLVED = SIDE * (math.sqrt(4.0 + 0.1 * math.pi) - 2.0) / math.pi
"""A square of side s buffered by d covers s^2 + 4 s d + pi d^2, so 10 per cent
more area is d = s (sqrt(4 + 0.1 pi) - 2) / pi: 201.3 m on 64.7 km2."""


def _staircase(cell: float = 75.0) -> Polygon:
    """A raster outline, the shape a delineated catchment actually has."""
    steps = [(0.0, 0.0)]
    for k in range(12):
        steps += [((k + 1) * cell * 3, k * cell * 2), ((k + 1) * cell * 3, (k + 1) * cell * 2)]
    return Polygon([*steps, (0.0, 12 * cell * 2)])


SHAPES = {
    "square": box(0.0, 0.0, 8000.0, 8000.0),
    "l_shape": Polygon([(0, 0), (6000, 0), (6000, 1500), (1500, 1500), (1500, 9000), (0, 9000)]),
    "staircase": _staircase(),
    "two_parts": MultiPolygon([box(0.0, 0.0, 3000.0, 2000.0), box(10_000.0, 0.0, 12_000.0, 4e3)]),
}


@pytest.fixture(scope="module")
def nancon_square(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("nancon")
    return write_features(folder / "watershed.shp", [box(0.0, 0.0, SIDE, SIDE)])


def _normalized(declared: object) -> object:
    return GeographicConfig.from_outlet(x=1.0, y=2.0, buff_area=declared).buff_area


def test_disk_buffer_distance() -> None:
    disk = Point(0.0, 0.0).buffer(3000.0, quad_segs=512)
    distance = buffer_distance_for_area_increase(disk, 0.10)
    assert distance == pytest.approx(3000.0 * (math.sqrt(1.1) - 1.0), abs=0.01)


@pytest.mark.parametrize("name", sorted(SHAPES))
@pytest.mark.parametrize("fraction", [0.10, 0.20])
def test_buffer_area_increase(name: str, fraction: float) -> None:
    shape = SHAPES[name]
    distance = buffer_distance_for_area_increase(shape, fraction)
    assert buffer_area_increase(shape, distance) == pytest.approx(fraction, abs=1.0e-4)
    # The Brunn-Minkowski bound: a disk of the same area needs the longest distance.
    area = shape.area
    assert distance <= math.sqrt((1.0 + fraction) * area / math.pi) - math.sqrt(area / math.pi)


@pytest.mark.parametrize(
    ("geometry", "fraction", "reason"),
    [(Polygon(), 0.1, "no area to enlarge"), (SHAPES["square"], 0.0, "must be > 0")],
)
def test_refused_increase(geometry, fraction, reason) -> None:
    with pytest.raises(ValueError, match=reason):
        buffer_distance_for_area_increase(geometry, fraction)


# 112.5 sits halfway between 75 and 150 and goes down; 37.5 goes down to zero
# and comes back up to the one-cell floor.
@pytest.mark.parametrize(
    ("declared", "resolution", "rule", "expected"),
    [
        ("10%", None, "area_percent", SQUARE_SOLVED), ("10%", 75.0, "area_percent", 225.0),
        (10, None, "legacy_sqrt_percent", 804.0), (10, 75.0, "legacy_sqrt_percent", 825.0),
        ("150 m", None, "distance", 150.0), ("10.0", None, "distance", 10.0), ("2 km", None, "distance", 2000.0),
        ("500 m", 75.0, "distance", 525.0), ("1 km", 75.0, "distance", 975.0), ("141.4 m", 75.0, "distance", 150.0),
        ("37.5 m", 75.0, "distance", 75.0), ("10 m", 75.0, "distance", 75.0), ("112.5 m", 75.0, "distance", 75.0),
        ("113 m", 75.0, "distance", 150.0),
    ],
)  # fmt: skip
def test_declared_buffer_rules(
    nancon_square, tmp_path, declared, resolution, rule, expected
) -> None:
    """The declared form goes through the config, then the domain is drawn on the square."""
    products = derive_catchment_domain(
        nancon_square, tmp_path, buff_area=_normalized(declared), dem_resolution=resolution
    )
    assert products.buffer_rule == rule
    assert products.buffer_distance_m == pytest.approx(expected, abs=0.01)
    if resolution is None:
        unsnapped = buffer_distance_m(box(0.0, 0.0, SIDE, SIDE), _normalized(declared))
        assert unsnapped == pytest.approx(expected, abs=0.01)


def test_bare_number_equals_explicit_form(nancon_square, tmp_path) -> None:
    """The migration writes ``10`` as ``"10% of sqrt(area)"`` and no distance moves."""
    for resolution in (None, 75.0):
        bare = derive_catchment_domain(
            nancon_square, tmp_path / "bare", buff_area=_normalized(10), dem_resolution=resolution
        )
        explicit = derive_catchment_domain(
            nancon_square,
            tmp_path / "explicit",
            buff_area=_normalized("10% of sqrt(area)"),
            dem_resolution=resolution,
        )
        assert explicit.buffer_rule == "sqrt_area"
        assert explicit.buffer_distance_m == bare.buffer_distance_m
        assert explicit.buffer_area_increase == bare.buffer_area_increase


def test_bare_distance_string_with_dem_on_disk(nancon_square, tmp_path) -> None:
    dem = write_geotiff(tmp_path / "dem.tif", [[1.0]], cell=75.0)
    products = derive_catchment_domain(nancon_square, tmp_path, buff_area="141.4", dem_path=dem)
    assert products.buffer_distance_m == 150.0


@pytest.mark.parametrize("declared", ["0%", "-5 m", "", "   ", 0, -3.0])
def test_refused_empty_buffer(declared: object) -> None:
    with pytest.raises(ValidationError):
        _normalized(declared)


def _bounds(path: str) -> tuple[float, ...]:
    return tuple(float(v) for v in gpd.read_file(path).total_bounds)


@pytest.mark.parametrize(("buff_area", "distance"), [(20.0, 200.0), ("150.0 m", 150.0)])
def test_box_and_buffered_box(tmp_path, buff_area, distance) -> None:
    catchment = write_features(tmp_path / "watershed.shp", [box(0.0, 0.0, 1000.0, 1000.0)])
    products = derive_catchment_domain(
        catchment, tmp_path / "out", buff_area=buff_area, dem_resolution=10.0
    )
    assert products.catchment_area_km2 == pytest.approx(1.0, abs=1e-12)
    assert products.buffer_distance_m == pytest.approx(distance)
    assert _bounds(products.watershed_box_shp) == pytest.approx((0.0, 0.0, 1000.0, 1000.0))
    framed = (-distance, -distance, 1000.0 + distance, 1000.0 + distance)
    assert _bounds(products.watershed_buff_shp) == pytest.approx(framed, abs=1e-6)
    assert _bounds(products.watershed_box_buff_shp) == pytest.approx(framed, abs=1e-6)


def test_products_record_the_margin(tmp_path: Path) -> None:
    shape = SHAPES["l_shape"]
    catchment = write_features(tmp_path / "watershed.shp", [shape])
    products = derive_catchment_domain(
        catchment, tmp_path / "out", buff_area="10%", dem_resolution=25.0
    )
    assert isinstance(products, CatchmentDomainProducts)
    assert (products.buffer_rule, products.buffer_declared) == ("area_percent", "10%")
    assert products.buffer_distance_m % 25.0 == 0.0
    assert products.buffer_area_increase == pytest.approx(0.10, abs=0.02)
    written = gpd.read_file(products.watershed_buff_shp).geometry.union_all()
    assert written.area >= shape.area
    assert written.area / shape.area - 1.0 == pytest.approx(products.buffer_area_increase, 1e-6)


def _catchment(tmp_path: Path, geometries: list, crs: str = "EPSG:2154") -> Path:
    return write_features(tmp_path / "watershed.shp", geometries, crs=crs)


@pytest.mark.parametrize(
    ("make", "options", "error", "reason"),
    [
        (lambda t: t / "gone.shp", {}, FileNotFoundError, "catchment_shp not found"),
        (lambda t: _catchment(t, []), {}, ValueError, "is empty"),
        (lambda t: _catchment(t, [box(0, 0, 1, 1)], "EPSG:4326"), {}, ValueError, "geographic"),
        (lambda t: _catchment(t, [Polygon()]), {}, ValueError, "area must be > 0"),
        (lambda t: _catchment(t, [box(0, 0, 10, 10)]), {"dem_resolution": 0.0}, ValueError, "> 0"),
        (lambda t: _catchment(t, [box(0, 0, 10, 10)]), {"buff_area": "10 kg"}, ValueError, "length"),
    ],
    ids=["missing", "empty", "degrees", "no area", "zero resolution", "not a length"],
)  # fmt: skip
def test_refusals(tmp_path, make, options, error, reason) -> None:
    with pytest.raises(error, match=reason):
        derive_catchment_domain(
            make(tmp_path), tmp_path / "out", **{"buff_area": "10 m", **options}
        )


def test_buffer_label() -> None:
    """The margin is a declared rule and a drawn distance, never an area in m2."""
    drawn = SimpleNamespace(buff_area="10%", buffer_distance_m=150.0, buffer_area_increase=0.106)
    unrecorded = SimpleNamespace(buff_area="10%", buffer_distance_m=None, buffer_area_increase=None)
    assert CatchmentDelineation.buffer_label(drawn) == "10% (150 m, +10.6% area)"
    assert CatchmentDelineation.buffer_label(unrecorded) == "10%"


@pytest.mark.parametrize(
    ("geometries", "columns", "stale"),
    [
        ([box(0.0, 0.0, 1000.0, 2000.0)], {}, None),
        ([box(0.0, 0.0, 1000.0, 2000.0)], {"AREA": [2.01e6]}, None),
        ([box(0.0, 0.0, 1000.0, 2000.0)], {"AREA": ["3.0e6"]}, None),
        ([box(0.0, 0.0, 1000.0, 2000.0)], {"AREA": [3.0e6]}, ("3 km2", "2 km2", "50.0%")),
        (
            [box(0.0, 0.0, 1000.0, 1000.0), box(0.0, 1000.0, 1000.0, 2000.0)],
            {"AREA": [-1.0e6, 2.0e6]},
            ("3 km2", "2 km2", "50.0%"),
        ),
    ],
    ids=["no-column", "column-within-1%", "text-column", "stale-column", "stale-in-two-rows"],
)
def test_catchment_area_and_stale_column(tmp_path, caplog, geometries, columns, stale) -> None:
    path = write_features(tmp_path / "watershed.shp", geometries, **columns)
    with caplog.at_level(logging.WARNING):
        assert compute_catchment_area_km2(path) == pytest.approx(2.0)
    warnings = [r.getMessage() for r in caplog.records if "AREA column" in r.getMessage()]
    if stale is None:
        assert warnings == []
    else:
        (message,) = warnings
        assert all(word in message for word in (str(path), *stale))


def test_catchment_area_refusals(tmp_path) -> None:
    parts = write_features(tmp_path / "two.shp", [box(0, 0, 1e3, 1e3), box(2e3, 0, 3e3, 3e3)])
    domain = derive_catchment_domain(parts, tmp_path / "out", buff_area="10 m")
    assert compute_catchment_area_km2(parts) == pytest.approx(domain.catchment_area_km2)
    degrees = write_features(tmp_path / "wgs84.shp", [box(-2.0, 48.0, -1.9, 48.1)], crs="EPSG:4326")
    with pytest.raises(TerrainProductError, match=r"wgs84\.shp.*EPSG:4326"):
        compute_catchment_area_km2(degrees)
    with pytest.raises(FileNotFoundError, match="not found"):
        compute_catchment_area_km2(tmp_path / "gone.shp")
    with pytest.raises(ValueError, match="empty"):
        compute_catchment_area_km2(write_features(tmp_path / "empty.shp", []))


def test_fine_disk_needs_a_wider_bracket() -> None:
    # A 16384-gon is so close to a disk that its chord buffer falls just short
    # of the Brunn-Minkowski distance, so the search widens the bracket.
    radius_m = 1000.0
    disk = Point(0.0, 0.0).buffer(radius_m, quad_segs=4096)
    distance = buffer_distance_for_area_increase(disk, 5.0)
    # pi (R + d)^2 = 6 pi R^2
    assert distance == pytest.approx(radius_m * (math.sqrt(6.0) - 1.0), rel=1.0e-4)
    assert buffer_area_increase(disk, distance) == pytest.approx(5.0, abs=1.0e-4)


@pytest.mark.parametrize(
    ("declared", "reason"),
    [("0 m", "distance must be > 0"), (0, "percentage must produce a distance > 0")],
)
def test_refused_zero_margin(declared, reason) -> None:
    with pytest.raises(ValueError, match=reason):
        buffer_distance_m(SHAPES["square"], declared)
