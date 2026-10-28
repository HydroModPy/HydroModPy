"""A buffer of N per cent makes the modelled catchment N per cent larger in area.

Abherve et al. (2023, HESS 27, p. 3224) enlarge "the modeled domain by 10 %".
The v1 code read the same "10" as 10 per cent of sqrt(area in km2) km, which on
the Nancon (64.7 km2) is 825 m and +53 per cent of area; the published Zenodo
code used yet another rule. The text is the only one of the three that means
what it says, so "N%" now solves that distance on the real polygon. A bare
number keeps the v1 rule, with a warning, so a sealed run replays its domain.
A distance form once lost its unit on the way and raised before it could be used.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import geopandas as gpd
import pytest
from pydantic import ValidationError
from shapely.geometry import MultiPolygon, Point, Polygon, box

from hydromodpy.spatial.geographic.core.catchment_domain import (
    CatchmentDomainProducts,
    buffer_area_increase,
    buffer_distance_for_area_increase,
    buffer_distance_m,
    derive_catchment_domain,
)
from hydromodpy.spatial.geographic.core.catchment_metrics import compute_catchment_area_km2
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from tests._helpers.geographic_cases import write_features
from tests._helpers.geotiffs import write_geotiff

NANCON_AREA_M2 = 64.7e6
SIDE = math.sqrt(NANCON_AREA_M2)
SQUARE_SOLVED = SIDE * (math.sqrt(4.0 + 0.1 * math.pi) - 2.0) / math.pi
"""A square of side s buffered by d covers s^2 + 4 s d + pi d^2, so 10 per cent
more area is d = s (sqrt(4 + 0.1 pi) - 2) / pi: 201.3 m on 64.7 km2."""


def _brunn_minkowski_bound(area: float, fraction: float) -> float:
    return math.sqrt((1.0 + fraction) * area / math.pi) - math.sqrt(area / math.pi)


def _staircase(cell: float = 75.0) -> Polygon:
    """A raster outline, the shape a delineated catchment actually has."""
    steps = [(0.0, 0.0)]
    for k in range(12):
        steps.append(((k + 1) * cell * 3, k * cell * 2))
        steps.append(((k + 1) * cell * 3, (k + 1) * cell * 2))
    steps.append((0.0, 12 * cell * 2))
    return Polygon(steps)


SHAPES = {
    "square": box(0.0, 0.0, 8000.0, 8000.0),
    "l_shape": Polygon([(0, 0), (6000, 0), (6000, 1500), (1500, 1500), (1500, 9000), (0, 9000)]),
    "staircase": _staircase(),
    "two_parts": MultiPolygon(
        [box(0.0, 0.0, 3000.0, 2000.0), box(10_000.0, 0.0, 12_000.0, 4000.0)]
    ),
}


@pytest.fixture(scope="module")
def nancon_square(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("nancon")
    return write_features(folder / "watershed.shp", [box(0.0, 0.0, SIDE, SIDE)])


def _normalized(declared: object) -> object:
    return GeographicConfig.from_outlet(x=1.0, y=2.0, dem="dem.tif", buff_area=declared).buff_area


# --- the distance a declared buffer draws -------------------------------------


def test_a_disk_is_solved_to_the_centimetre() -> None:
    radius = 3000.0
    disk = Point(0.0, 0.0).buffer(radius, quad_segs=512)

    distance = buffer_distance_for_area_increase(disk, 0.10)

    assert distance == pytest.approx(radius * (math.sqrt(1.1) - 1.0), abs=0.01)


@pytest.mark.parametrize("name", sorted(SHAPES))
@pytest.mark.parametrize("fraction", [0.10, 0.20])
def test_every_shape_gets_the_area_it_declares(name: str, fraction: float) -> None:
    shape = SHAPES[name]

    distance = buffer_distance_for_area_increase(shape, fraction)

    assert buffer_area_increase(shape, distance) == pytest.approx(fraction, abs=1.0e-4)
    assert distance <= _brunn_minkowski_bound(shape.area, fraction)


@pytest.mark.parametrize(
    ("geometry", "fraction", "reason"),
    [(Polygon(), 0.1, "no area to enlarge"), (SHAPES["square"], 0.0, "must be > 0")],
)
def test_an_increase_that_cannot_be_solved_is_refused(geometry, fraction, reason) -> None:
    with pytest.raises(ValueError, match=reason):
        buffer_distance_for_area_increase(geometry, fraction)


@pytest.mark.parametrize(
    ("declared", "resolution", "rule", "expected"),
    [
        ("10%", None, "area_percent", SQUARE_SOLVED),
        ("10%", 75.0, "area_percent", 225.0),
        (10, None, "legacy_sqrt_percent", 804.0),
        (10, 75.0, "legacy_sqrt_percent", 825.0),
        ("150 m", None, "distance", 150.0),
        ("10.0", None, "distance", 10.0),
        ("2 km", None, "distance", 2000.0),
        ("500 m", 75.0, "distance", 525.0),
        ("1 km", 75.0, "distance", 975.0),
        # 112.5 sits halfway between 75 and 150 and goes down; 37.5 goes down to
        # zero and comes back up to the one-cell floor.
        ("141.4 m", 75.0, "distance", 150.0),
        ("37.5 m", 75.0, "distance", 75.0),
        ("10 m", 75.0, "distance", 75.0),
        ("112.5 m", 75.0, "distance", 75.0),
        ("113 m", 75.0, "distance", 150.0),
    ],
)
def test_a_declared_buffer_draws_its_rule_snapped_to_the_dem_grid(
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


def test_a_percent_and_a_bare_number_stay_two_different_distances() -> None:
    """No later refactor may glue the paper's rule back onto the v1 one."""
    square = box(0.0, 0.0, SIDE, SIDE)

    assert buffer_distance_m(square, _normalized("10%")) != buffer_distance_m(
        square, _normalized(10)
    )
    assert buffer_distance_m(square, _normalized("10 m")) != buffer_distance_m(
        square, _normalized("10%")
    )


def test_a_sealed_bare_distance_string_and_a_dem_on_disk_read_as_metres_and_cells(
    nancon_square, tmp_path
) -> None:
    dem = write_geotiff(tmp_path / "dem.tif", [[1.0]], cell=75.0)

    products = derive_catchment_domain(
        nancon_square, tmp_path, buff_area="141.4", dem_init_path=dem
    )

    assert products.buffer_distance_m == 150.0


# --- the config writes one form per rule --------------------------------------


@pytest.mark.parametrize(
    ("declared", "normalized"),
    [
        ("10%", "10%"),
        ("10 %", "10%"),
        (" 12.5% ", "12.5%"),
        ("150 m", "150.0 m"),
        ("0.15 km", "150.0 m"),
        ("150", "150.0 m"),
        ("10.0", "10.0 m"),
        (10, 10.0),
        (10.0, 10.0),
    ],
)
def test_the_config_writes_one_form_per_rule_and_reads_it_back(declared, normalized) -> None:
    once = _normalized(declared)

    assert once == normalized
    assert type(once) is type(normalized)
    assert _normalized(once) == once
    config = GeographicConfig.from_outlet(x=1.0, y=2.0, dem="dem.tif", buff_area=declared)
    replayed = GeographicConfig.model_validate(config.model_dump(mode="json"))
    assert replayed.buff_area == config.buff_area
    assert type(replayed.buff_area) is type(config.buff_area)


@pytest.mark.parametrize("declared", ["0%", "-5 m", "", "   ", 0, -3.0])
def test_the_config_refuses_a_buffer_with_no_margin(declared: object) -> None:
    with pytest.raises(ValidationError):
        _normalized(declared)


def test_the_factories_default_to_the_paper_rule() -> None:
    assert GeographicConfig.from_outlet(x=1.0, y=2.0, dem="dem.tif").buff_area == "10%"


# --- the domain written on disk -----------------------------------------------


def _bounds(path: str) -> tuple[float, ...]:
    return tuple(float(v) for v in gpd.read_file(path).total_bounds)


@pytest.mark.parametrize(("buff_area", "distance"), [(20.0, 200.0), ("150.0 m", 150.0)])
def test_the_box_and_the_buffered_box_frame_the_catchment(tmp_path, buff_area, distance) -> None:
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


def test_a_bare_number_keeps_the_v1_domain_and_says_so(nancon_square, tmp_path, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        products = derive_catchment_domain(
            nancon_square, tmp_path, buff_area=10.0, dem_resolution=75.0
        )

    assert products.buffer_distance_m == 825.0
    legacy = [record for record in caplog.records if "legacy v1 rule" in record.getMessage()]
    assert len(legacy) == 1
    assert '"10%"' in legacy[0].getMessage()
    assert '"825 m"' in legacy[0].getMessage()


def test_the_products_say_how_the_margin_was_chosen(tmp_path: Path) -> None:
    catchment = write_features(tmp_path / "watershed.shp", [SHAPES["l_shape"]])

    products = derive_catchment_domain(
        catchment, tmp_path / "out", buff_area="10%", dem_resolution=25.0
    )

    assert isinstance(products, CatchmentDomainProducts)
    assert products.buffer_rule == "area_percent"
    assert products.buffer_declared == "10%"
    assert products.buffer_distance_m % 25.0 == 0.0
    assert products.buffer_area_increase == pytest.approx(0.10, abs=0.02)
    written = gpd.read_file(products.watershed_buff_shp).geometry.union_all()
    assert written.area >= SHAPES["l_shape"].area
    assert written.area / SHAPES["l_shape"].area - 1.0 == pytest.approx(
        products.buffer_area_increase, rel=1.0e-6
    )


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
        (
            lambda t: _catchment(t, [box(0, 0, 10, 10)]),
            {"buff_area": "10 kg"},
            ValueError,
            "length",
        ),
    ],
    ids=["missing", "empty", "degrees", "no area", "zero resolution", "not a length"],
)
def test_a_catchment_that_cannot_be_buffered_is_refused(
    tmp_path, make, options, error, reason
) -> None:
    options = {"buff_area": "10 m", **options}

    with pytest.raises(error, match=reason):
        derive_catchment_domain(make(tmp_path), tmp_path / "out", **options)


def test_the_delineation_shows_the_declared_margin_and_what_it_drew() -> None:
    """The margin is a declared rule and a drawn distance, never an area in m2."""
    from types import SimpleNamespace

    from hydromodpy.spatial.geographic.catchment_delineation import CatchmentDelineation

    drawn = SimpleNamespace(buff_area="10%", buffer_distance_m=150.0, buffer_area_increase=0.106)
    unrecorded = SimpleNamespace(buff_area="10%", buffer_distance_m=None, buffer_area_increase=None)

    assert CatchmentDelineation._buffer_label(drawn) == "10% (150 m, +10.6% area)"
    assert CatchmentDelineation._buffer_label(unrecorded) == "10%"


# --- the catchment area -------------------------------------------------------


def test_the_catchment_area_reads_the_area_field_else_the_geometry(tmp_path) -> None:
    square = box(0.0, 0.0, 1000.0, 2000.0)
    plain = write_features(tmp_path / "plain.shp", [square])
    halves = [box(0.0, 0.0, 1000.0, 1000.0), box(0.0, 1000.0, 1000.0, 2000.0)]
    declared = write_features(tmp_path / "declared.shp", halves, AREA=[-1.0e6, 2.0e6])
    text = write_features(tmp_path / "text.shp", [square], AREA=["3.0e6"])

    assert compute_catchment_area_km2(plain) == pytest.approx(2.0)
    assert compute_catchment_area_km2(declared) == pytest.approx(3.0)
    assert compute_catchment_area_km2(text) == pytest.approx(2.0)
    with pytest.raises(FileNotFoundError, match="not found"):
        compute_catchment_area_km2(tmp_path / "gone.shp")
    with pytest.raises(ValueError, match="empty"):
        compute_catchment_area_km2(write_features(tmp_path / "empty.shp", []))


def test_the_catchment_area_of_a_watershed_in_two_parts_is_the_one_the_domain_uses(
    tmp_path,
) -> None:
    parts = write_features(
        tmp_path / "watershed.shp", [box(0, 0, 1000, 1000), box(2000, 0, 3000, 3000)]
    )

    domain = derive_catchment_domain(parts, tmp_path / "out", buff_area="10 m")

    assert compute_catchment_area_km2(parts) == pytest.approx(domain.catchment_area_km2)
