"""The value types and refusals of the terrain port."""

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


def _accumulation(transform: str):
    return type("Acc", (), {"transform": transform})()


@pytest.mark.parametrize("distance", [0.0, -25.0])
def test_a_snap_window_of_no_width_is_refused(distance) -> None:
    with pytest.raises(TerrainRequestError, match="snap distance"):
        snap_window_cells(distance, dx=25.0, dy=25.0)


def test_a_conditioning_extent_says_what_it_conditions() -> None:
    assert ConditioningExtent.per_outlet_buffer(500.0).buffer_distance_m == 500.0


@pytest.mark.parametrize(
    ("kind", "distance", "match"),
    [
        ("everywhere", None, "Unknown conditioning extent"),
        ("regional", 100.0, "carries no buffer distance"),
        ("per_outlet_buffer", 0.0, "needs a buffer distance"),
    ],
)
def test_a_conditioning_extent_that_contradicts_itself_is_refused(kind, distance, match) -> None:
    with pytest.raises(TerrainRequestError, match=match):
        ConditioningExtent(kind=kind, buffer_distance_m=distance)


@pytest.mark.parametrize(
    ("outlet_id", "match"),
    [("../up", "not usable as a directory name"), ("a" * 65, "over the 64")],
)
def test_an_outlet_id_that_makes_no_directory_name_is_refused(outlet_id, match) -> None:
    with pytest.raises(TerrainRequestError, match=match):
        Outlet(outlet_id=outlet_id, x=0.0, y=0.0)


CAPPED = CappedBreach(max_depth_m=0.5, max_distance_m=200.0)
REGIONAL = ConditioningExtent.regional()


def test_the_conditioning_method_holds_four_kinds_of_value() -> None:
    literal, capped = get_args(ConditioningMethod)
    assert get_args(literal) == ("fill", "breach", "provided")
    assert capped is CappedBreach


@pytest.mark.parametrize(
    ("serves", "method", "extent", "error", "match"),
    [
        (("fill",), "fill", REGIONAL, None, None),
        (("fill", "breach", "capped"), CAPPED, REGIONAL, None, None),
        (("fill",), "breach", REGIONAL, TerrainCapabilityError, "breach"),
        (("fill",), CAPPED, REGIONAL, TerrainCapabilityError, "capped breach"),
        (("fill", "breach", "capped"), "carve", REGIONAL, TerrainCapabilityError, "'carve'"),
        (("fill",), "provided", REGIONAL, TerrainRequestError, r"ConditionedDem\.provided"),
        (
            ("fill", "breach", "capped"),
            "provided",
            REGIONAL,
            TerrainRequestError,
            r"ConditionedDem\.provided",
        ),
        (
            ("fill",),
            "fill",
            ConditioningExtent.per_outlet_buffer(500.0),
            TerrainCapabilityError,
            "per_outlet_buffer",
        ),
    ],
    ids=[
        "fill",
        "capped",
        "numpy-breach",
        "numpy-capped",
        "unknown-method",
        "numpy-provided",
        "whitebox-provided",
        "buffer-extent",
    ],
)
def test_a_conditioning_an_engine_does_not_serve_is_refused_by_name(
    serves, method, extent, error, match
) -> None:
    if error is None:
        require_conditioning("engine_x", method, extent, serves=serves)
        return
    with pytest.raises(error, match=match):
        require_conditioning("engine_x", method, extent, serves=serves)


@pytest.mark.parametrize(
    ("units", "transform", "served"),
    [
        ("cells", "none", True),
        ("m2", "ln", True),
        ("km2", "none", False),
        ("cells", "log10", False),
    ],
)
def test_an_accumulation_is_served_in_two_units_and_two_transforms(
    units, transform, served
) -> None:
    if served:
        require_accumulation("engine_x", units, transform)
        return
    with pytest.raises(TerrainCapabilityError, match="not implemented"):
        require_accumulation("engine_x", units, transform)


def _streams_of(accumulation, threshold: float = 20.0) -> StreamNetwork:
    return StreamNetwork(
        accumulation.path.with_name("streams.tif"),
        threshold,
        accumulation.units,
        accumulation.directions,
    )


@pytest.mark.parametrize(
    ("transform", "threshold", "error", "match"),
    [
        ("none", 20.0, None, None),
        ("ln", 20.0, TerrainProductError, "untransformed"),
        ("none", 0.0, TerrainRequestError, "must be > 0"),
    ],
)
def test_a_stream_threshold_needs_a_raw_accumulation_and_a_positive_value(
    transform, threshold, error, match
) -> None:
    accumulation = fake_accumulation(transform=transform)
    if error is None:
        require_stream(accumulation, threshold)
        return
    with pytest.raises(error, match=match):
        require_stream(accumulation, threshold)


OUTLET = Outlet("exit", 10.0, 20.0)
FLAT = CatchmentLayout.flat(mask_name="mask.tif", boundary_name="boundary.shp")


def _delineable(accumulation=None, outlets=(OUTLET,), **options) -> None:
    request = {"snap": "window", "snap_distance_m": 25.0, "layout": CatchmentLayout.per_outlet()}
    require_delineable(
        accumulation or fake_accumulation(transform="none"), outlets, **request | options
    )


@pytest.mark.parametrize(
    ("accumulation", "outlets", "options", "error", "match"),
    [
        (None, (), {}, TerrainRequestError, "at least one outlet"),
        (None, (OUTLET,), {"snap_distance_m": 0.0}, TerrainRequestError, "snap distance"),
        (None, (OUTLET, replace(OUTLET, x=1.0)), {}, TerrainRequestError, "repeated: exit"),
        (
            None,
            (OUTLET, replace(OUTLET, outlet_id="EXIT")),
            {},
            TerrainRequestError,
            "case-folded",
        ),
        (
            None,
            (OUTLET, Outlet("b", 1.0, 1.0)),
            {"layout": FLAT},
            TerrainRequestError,
            "flat layout",
        ),
        (None, (OUTLET,), {"snap": "nearest"}, TerrainRequestError, "Unknown snap method"),
        (
            fake_accumulation(transform="rank_destroying"),
            (OUTLET,),
            {},
            TerrainProductError,
            "order of the cells",
        ),
        (
            replace(fake_accumulation(transform="ln"), units="m2"),
            (OUTLET,),
            {},
            TerrainProductError,
            "only in 'cells'",
        ),
    ],
    ids=[
        "empty-batch",
        "no-snap-width",
        "same-id-twice",
        "ids-differ-by-case",
        "flat-layout-with-a-batch",
        "unknown-snap",
        "transform-breaks-the-order",
        "transformed-square-metres",
    ],
)
def test_a_delineation_the_port_cannot_answer_is_refused_before_any_write(
    accumulation, outlets, options, error, match
) -> None:
    with pytest.raises(error, match=match):
        _delineable(accumulation, outlets, **options)


def test_a_jenson_snap_needs_the_network_of_the_pointer_it_delineates_down() -> None:
    accumulation = fake_accumulation(transform="none")
    own = JensonSnap(_streams_of(accumulation))
    other = replace(accumulation.directions, path=accumulation.directions.path.with_name("o.tif"))
    foreign = JensonSnap(replace(own.streams, directions=other))
    _delineable(accumulation, snap=own)
    with pytest.raises(TerrainProductError, match="another pointer"):
        _delineable(accumulation, snap=foreign)


def test_a_jenson_snap_ranks_no_accumulation_so_a_transform_does_not_matter() -> None:
    accumulation = fake_accumulation(transform="rank_destroying")
    _delineable(accumulation, snap=JensonSnap(_streams_of(accumulation)))


def test_the_digest_is_the_hash_of_the_id_the_version_and_the_pointer_table() -> None:
    expected = hashlib.sha256(b"engine_x\n1.2.3\nd8_wbt").hexdigest()
    assert stamp("engine_x", "1.2.3") == expected
    assert stamp("engine_x", "1.2.3", "d8_esri") != expected
    assert stamp("engine_y", "1.2.3") != expected


REPORT = CappedBreachReport(12, 3, 0.52, 0.1, 8, 0.5, 0.01)


@pytest.mark.parametrize(
    ("change", "error"),
    [({"written_by_a_later_version": 1.0}, None), ({"max_cost_m": None}, KeyError)],
    ids=["a-key-too-many", "a-key-missing"],
)
def test_a_breach_report_document_is_read_with_tolerance(change, error) -> None:
    """A cache manifest written by an older or newer build must still read back."""
    document = {**REPORT.to_document(), **change}
    if error is None:
        assert CappedBreachReport.from_document(document) == REPORT
        return
    del document["max_cost_m"]
    with pytest.raises(error):
        CappedBreachReport.from_document(document)


def test_a_catchment_is_counted_and_measured_from_its_files(tmp_path) -> None:
    mask = np.full((4, 4), -32768, dtype="int16")
    mask[:2, :3] = 1
    mask_path = write_geotiff(tmp_path / "mask.tif", mask, cell=10.0, nodata=-32768)
    boundary_path = tmp_path / "boundary.shp"
    gpd.GeoDataFrame({"v": [1]}, geometry=[box(0, 20, 30, 40)], crs="EPSG:2154").to_file(
        boundary_path
    )
    found = Catchment.from_files(OUTLET, mask_path, boundary_path, 13.0, 24.0)
    assert (found.cell_count, found.area_m2) == (6, 600.0)
    assert found.snap_distance_m == pytest.approx(5.0)
    assert (found.snapped_x, found.snapped_y) == (13.0, 24.0)
