"""A buffer of N per cent makes the modelled catchment N per cent larger in area.

Abherve et al. (2023, HESS 27, p. 3224) enlarge "the modeled domain by 10 %".
The v1 code read the same "10" as 10 per cent of sqrt(area in km2) km, which on
the Nancon (64.7 km2) is 825 m and +53 per cent of area; the published Zenodo
code used yet another rule. The text is the only one of the three that means
what it says, so "N%" now solves that distance on the real polygon. A bare
number keeps the v1 rule, with a warning, so a sealed run replays its domain.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import MultiPolygon, Point, Polygon, box

from hydromodpy.spatial.geographic.core.catchment_domain import (
    CatchmentDomainProducts,
    _compute_buffer_distance,
    _snap_to_resolution,
    buffer_area_increase,
    buffer_distance_for_area_increase,
    derive_catchment_domain,
)
from hydromodpy.spatial.geographic.geographic_config import (
    GeographicConfig,
    _normalize_buff_area,
)

CRS = "EPSG:2154"
NANCON_AREA_M2 = 64.7e6


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
    ("raw", "expected"),
    [(141.4, 150.0), (37.5, 75.0), (10.0, 75.0), (112.5, 75.0), (113.0, 150.0)],
)
def test_the_distance_snaps_to_the_closest_cell_multiple(raw: float, expected: float) -> None:
    # 112.5 sits halfway between 75 and 150 and goes down; 37.5 goes down to
    # zero and comes back up to the one-cell floor.
    assert _snap_to_resolution(raw, 75.0) == expected


def test_a_percent_on_a_square_is_the_root_of_its_area_equation() -> None:
    # A square of side s buffered by d covers s^2 + 4 s d + pi d^2, so 10 per
    # cent more area is d = s (sqrt(4 + 0.1 pi) - 2) / pi: 201.3 m on 64.7 km2,
    # snapped to 225 m at 75 m. A real outline has a longer perimeter; the
    # Nancon polygon gives 141.4 m, snapped to 150 m.
    side = math.sqrt(NANCON_AREA_M2)
    square = box(0.0, 0.0, side, side)
    exact = side * (math.sqrt(4.0 + 0.1 * math.pi) - 2.0) / math.pi

    solved = _compute_buffer_distance(catchment=square, buff_area="10%", dem_resolution=None)
    snapped = _compute_buffer_distance(catchment=square, buff_area="10%", dem_resolution=75.0)

    assert solved == pytest.approx(exact, abs=0.01)
    assert snapped == 225.0


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
def test_the_normalizer_writes_one_form_per_rule(declared: object, normalized: object) -> None:
    once = _normalize_buff_area(declared)

    assert once == normalized
    assert type(once) is type(normalized)
    assert _normalize_buff_area(once) == once


@pytest.mark.parametrize("declared", ["0%", "-5 m", "", "   ", 0, -3.0])
def test_the_normalizer_refuses_what_has_no_margin(declared: object) -> None:
    with pytest.raises(ValueError):
        _normalize_buff_area(declared)


@pytest.mark.parametrize("declared", ["10%", "150 m", 10.0])
def test_a_sealed_config_reads_back_the_same_rule(declared: object) -> None:
    config = GeographicConfig.from_outlet(x=1.0, y=2.0, dem="dem.tif", buff_area=declared)

    replayed = GeographicConfig.model_validate(config.model_dump(mode="json"))

    assert replayed.buff_area == config.buff_area
    assert type(replayed.buff_area) is type(config.buff_area)


def test_the_factories_default_to_the_paper_rule() -> None:
    assert GeographicConfig.from_outlet(x=1.0, y=2.0, dem="dem.tif").buff_area == "10%"


def _write(geometry, path: Path) -> Path:
    gpd.GeoDataFrame({"id": [1]}, geometry=[geometry], crs=CRS).to_file(str(path))
    return path


def test_a_bare_number_keeps_the_v1_domain_and_says_so(tmp_path: Path, caplog) -> None:
    side = math.sqrt(NANCON_AREA_M2)
    catchment = _write(box(0.0, 0.0, side, side), tmp_path / "watershed.shp")

    with caplog.at_level(logging.WARNING):
        products = derive_catchment_domain(
            catchment, tmp_path / "out", buff_area=10.0, dem_resolution=75.0
        )

    assert products.buffer_distance_m == 825.0
    legacy = [record for record in caplog.records if "legacy v1 rule" in record.getMessage()]
    assert len(legacy) == 1
    assert '"10%"' in legacy[0].getMessage()
    assert '"825 m"' in legacy[0].getMessage()


def test_the_products_say_how_the_margin_was_chosen(tmp_path: Path) -> None:
    catchment = _write(SHAPES["l_shape"], tmp_path / "watershed.shp")

    products = derive_catchment_domain(
        catchment, tmp_path / "out", buff_area="10%", dem_resolution=25.0
    )

    assert isinstance(products, CatchmentDomainProducts)
    assert products.buffer_rule == "area_percent"
    assert products.buffer_declared == "10%"
    assert products.buffer_distance_m % 25.0 == 0.0
    assert products.buffer_area_increase == pytest.approx(0.10, abs=0.02)
    written = gpd.read_file(products.watershed_buff_shp).geometry.union_all()
    assert written.area / SHAPES["l_shape"].area - 1.0 == pytest.approx(
        products.buffer_area_increase, rel=1.0e-6
    )


def test_a_distance_is_published_as_a_distance(tmp_path: Path) -> None:
    catchment = _write(SHAPES["square"], tmp_path / "watershed.shp")

    products = derive_catchment_domain(catchment, tmp_path / "out", buff_area="150.0 m")

    assert products.buffer_rule == "distance"
    assert products.buffer_declared == "150.0 m"
    assert products.buffer_distance_m == 150.0


def test_a_percent_and_a_bare_number_stay_two_different_distances() -> None:
    """No later refactor may glue the paper's rule back onto the v1 one."""
    side = math.sqrt(NANCON_AREA_M2)
    square = box(0.0, 0.0, side, side)

    as_percent = _compute_buffer_distance(
        catchment=square, buff_area=_normalize_buff_area("10%"), dem_resolution=75.0
    )
    as_number = _compute_buffer_distance(
        catchment=square, buff_area=_normalize_buff_area(10), dem_resolution=75.0
    )

    assert as_percent == 225.0
    assert as_number == 825.0


def test_the_delineation_shows_the_declared_margin_and_what_it_drew() -> None:
    """The margin is a declared rule and a drawn distance, never an area in m2."""
    from types import SimpleNamespace

    from hydromodpy.spatial.geographic.catchment_delineation import CatchmentDelineation

    drawn = SimpleNamespace(buff_area="10%", buffer_distance_m=150.0, buffer_area_increase=0.106)
    unrecorded = SimpleNamespace(buff_area="10%", buffer_distance_m=None, buffer_area_increase=None)

    assert CatchmentDelineation._buffer_label(drawn) == "10% (150 m, +10.6% area)"
    assert CatchmentDelineation._buffer_label(unrecorded) == "10%"
