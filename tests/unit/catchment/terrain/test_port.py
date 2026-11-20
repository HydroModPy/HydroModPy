"""Value types and refusals of the terrain port.

The port names what an engine can serve (conditioning methods, accumulation units
in cells or m2, stream thresholds, delineation requests) and refuses the rest
before any file is written. Distances are in m.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import get_args

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from hydromodpy.catchment.terrain.port import (
    CappedBreach,
    CappedBreachReport,
    Catchment,
    CatchmentLayout,
    ConditioningExtent,
    ConditioningMethod,
    JensonSnap,
    Outlet,
    StreamNetwork,
    require_accumulation,
    require_conditioning,
    require_delineable,
    require_stream,
    snap_window_cells,
    stamp,
)
from hydromodpy.core.exceptions import (
    TerrainCapabilityError,
    TerrainProductError,
    TerrainRequestError,
)
from tests._helpers.geotiffs import write_geotiff
from tests._helpers.terrain_doubles import fake_accumulation

OUTLET = Outlet("exit", 10.0, 20.0)
FLAT = CatchmentLayout.flat(mask_name="mask.tif", boundary_name="boundary.shp")
CAPPED = CappedBreach(max_depth_m=0.5, max_distance_m=200.0)
REGIONAL = ConditioningExtent.regional()
REPORT = CappedBreachReport(12, 3, 0.52, 0.1, 8, 0.5, 0.01)


def streams_of(accumulation, threshold=20.0):
    return StreamNetwork(
        accumulation.path.with_name("streams.tif"),
        threshold,
        accumulation.units,
        accumulation.directions,
    )


def delineable(accumulation=None, outlets=(OUTLET,), **options):
    request = {"snap": "window", "snap_distance_m": 25.0, "layout": CatchmentLayout.per_outlet()}
    require_delineable(
        accumulation or fake_accumulation(transform="none"), outlets, **request | options
    )


def test_conditioning_extent_buffer():
    assert ConditioningExtent.per_outlet_buffer(500.0).buffer_distance_m == 500.0


def test_conditioning_method_kinds():
    literal, capped = get_args(ConditioningMethod)
    assert get_args(literal) == ("fill", "breach", "provided")
    assert capped is CappedBreach


SERVED_CONDITIONING = [
    pytest.param(("fill",), "fill", id="fill"),
    pytest.param(("fill", "breach", "capped"), CAPPED, id="capped"),
]


@pytest.mark.parametrize(("serves", "method"), SERVED_CONDITIONING)
def test_conditioning_served(serves, method):
    require_conditioning("engine_x", method, REGIONAL, serves=serves)


SERVED_ACCUMULATION = [
    pytest.param("cells", "none", id="cells raw"),
    pytest.param("m2", "ln", id="m2 ln"),
]


@pytest.mark.parametrize(("units", "transform"), SERVED_ACCUMULATION)
def test_accumulation_served(units, transform):
    require_accumulation("engine_x", units, transform)


def test_stream_threshold_served():
    require_stream(fake_accumulation(transform="none"), 20.0)


def test_jenson_snap_on_own_pointer():
    accumulation = fake_accumulation(transform="none")
    delineable(accumulation, snap=JensonSnap(streams_of(accumulation)))


def test_jenson_snap_ignores_transform():
    # It ranks no accumulation, so a rank-destroying transform does not matter.
    accumulation = fake_accumulation(transform="rank_destroying")
    delineable(accumulation, snap=JensonSnap(streams_of(accumulation)))


def test_stamp_hashes_id_version_pointer():
    expected = hashlib.sha256(b"engine_x\n1.2.3\nd8_wbt").hexdigest()
    assert stamp("engine_x", "1.2.3") == expected
    assert stamp("engine_x", "1.2.3", "d8_esri") != expected
    assert stamp("engine_y", "1.2.3") != expected


def test_breach_report_tolerates_extra_key():
    # A cache manifest written by a newer build must still read back.
    document = {**REPORT.to_document(), "written_by_a_later_version": 1.0}
    assert CappedBreachReport.from_document(document) == REPORT


def test_catchment_from_files(tmp_path):
    mask = np.full((4, 4), -32768, dtype="int16")
    mask[:2, :3] = 1  # 6 cells of 10 m
    mask_path = write_geotiff(tmp_path / "mask.tif", mask, cell=10.0, nodata=-32768)
    boundary_path = tmp_path / "boundary.shp"
    gpd.GeoDataFrame({"v": [1]}, geometry=[box(0, 20, 30, 40)], crs="EPSG:2154").to_file(
        boundary_path
    )

    found = Catchment.from_files(OUTLET, mask_path, boundary_path, 13.0, 24.0)

    assert (found.cell_count, found.area_m2) == (6, 600.0)
    assert found.snap_distance_m == pytest.approx(5.0)  # (3, 4) m from the outlet
    assert (found.snapped_x, found.snapped_y) == (13.0, 24.0)


@pytest.mark.parametrize("distance", [0.0, -25.0])
def test_snap_window_refusals(distance):
    with pytest.raises(TerrainRequestError, match="snap distance"):
        snap_window_cells(distance, dx=25.0, dy=25.0)


EXTENT_REFUSALS = [
    pytest.param("everywhere", None, "Unknown conditioning extent", id="unknown kind"),
    pytest.param("regional", 100.0, "carries no buffer distance", id="regional with buffer"),
    pytest.param("per_outlet_buffer", 0.0, "needs a buffer distance", id="buffer of zero"),
]


@pytest.mark.parametrize(("kind", "distance", "match"), EXTENT_REFUSALS)
def test_extent_refusals(kind, distance, match):
    with pytest.raises(TerrainRequestError, match=match):
        ConditioningExtent(kind=kind, buffer_distance_m=distance)


OUTLET_ID_REFUSALS = [
    pytest.param("../up", "not usable as a directory name", id="path"),
    pytest.param("a" * 65, "over the 64", id="too long"),
]


@pytest.mark.parametrize(("outlet_id", "match"), OUTLET_ID_REFUSALS)
def test_outlet_id_refusals(outlet_id, match):
    with pytest.raises(TerrainRequestError, match=match):
        Outlet(outlet_id=outlet_id, x=0.0, y=0.0)


CONDITIONING_REFUSALS = [
    pytest.param(("fill",), "breach", REGIONAL, TerrainCapabilityError, "breach", id="breach"),
    pytest.param(("fill",), CAPPED, REGIONAL, TerrainCapabilityError, "capped breach", id="capped"),
    pytest.param(
        ("fill", "breach", "capped"),
        "carve",
        REGIONAL,
        TerrainCapabilityError,
        "'carve'",
        id="unknown method",
    ),
    pytest.param(
        ("fill",),
        "provided",
        REGIONAL,
        TerrainRequestError,
        r"ConditionedDem\.provided",
        id="provided with fill only",
    ),
    pytest.param(
        ("fill", "breach", "capped"),
        "provided",
        REGIONAL,
        TerrainRequestError,
        r"ConditionedDem\.provided",
        id="provided with all",
    ),
    pytest.param(
        ("fill",),
        "fill",
        ConditioningExtent.per_outlet_buffer(500.0),
        TerrainCapabilityError,
        "per_outlet_buffer",
        id="buffer extent",
    ),
]


@pytest.mark.parametrize(("serves", "method", "extent", "error", "match"), CONDITIONING_REFUSALS)
def test_conditioning_refusals(serves, method, extent, error, match):
    with pytest.raises(error, match=match):
        require_conditioning("engine_x", method, extent, serves=serves)


ACCUMULATION_REFUSALS = [
    pytest.param("km2", "none", id="km2"),
    pytest.param("cells", "log10", id="log10"),
]


@pytest.mark.parametrize(("units", "transform"), ACCUMULATION_REFUSALS)
def test_accumulation_refusals(units, transform):
    with pytest.raises(TerrainCapabilityError, match="not implemented"):
        require_accumulation("engine_x", units, transform)


STREAM_REFUSALS = [
    pytest.param("ln", 20.0, TerrainProductError, "untransformed", id="transformed"),
    pytest.param("none", 0.0, TerrainRequestError, "must be > 0", id="threshold of zero"),
]


@pytest.mark.parametrize(("transform", "threshold", "error", "match"), STREAM_REFUSALS)
def test_stream_refusals(transform, threshold, error, match):
    with pytest.raises(error, match=match):
        require_stream(fake_accumulation(transform=transform), threshold)


DELINEATION_REFUSALS = [
    pytest.param(None, (), {}, TerrainRequestError, "at least one outlet", id="empty batch"),
    pytest.param(
        None,
        (OUTLET,),
        {"snap_distance_m": 0.0},
        TerrainRequestError,
        "snap distance",
        id="no snap width",
    ),
    pytest.param(
        None,
        (OUTLET, replace(OUTLET, x=1.0)),
        {},
        TerrainRequestError,
        "repeated: exit",
        id="same id twice",
    ),
    pytest.param(
        None,
        (OUTLET, replace(OUTLET, outlet_id="EXIT")),
        {},
        TerrainRequestError,
        "case-folded",
        id="ids differ by case",
    ),
    pytest.param(
        None,
        (OUTLET, Outlet("b", 1.0, 1.0)),
        {"layout": FLAT},
        TerrainRequestError,
        "flat layout",
        id="flat layout with a batch",
    ),
    pytest.param(
        None,
        (OUTLET,),
        {"snap": "nearest"},
        TerrainRequestError,
        "Unknown snap method",
        id="unknown snap",
    ),
    pytest.param(
        fake_accumulation(transform="rank_destroying"),
        (OUTLET,),
        {},
        TerrainProductError,
        "order of the cells",
        id="transform breaks the order",
    ),
    pytest.param(
        replace(fake_accumulation(transform="ln"), units="m2"),
        (OUTLET,),
        {},
        TerrainProductError,
        "only in 'cells'",
        id="transformed square metres",
    ),
]


@pytest.mark.parametrize(
    ("accumulation", "outlets", "options", "error", "match"), DELINEATION_REFUSALS
)
def test_delineation_refusals(accumulation, outlets, options, error, match):
    with pytest.raises(error, match=match):
        delineable(accumulation, outlets, **options)


def test_jenson_snap_foreign_pointer_refused():
    accumulation = fake_accumulation(transform="none")
    own = JensonSnap(streams_of(accumulation))
    other = replace(accumulation.directions, path=accumulation.directions.path.with_name("o.tif"))
    foreign = JensonSnap(replace(own.streams, directions=other))

    with pytest.raises(TerrainProductError, match="another pointer"):
        delineable(accumulation, snap=foreign)


def test_breach_report_missing_key_refused():
    document = REPORT.to_document()
    del document["max_cost_m"]

    with pytest.raises(KeyError):
        CappedBreachReport.from_document(document)
