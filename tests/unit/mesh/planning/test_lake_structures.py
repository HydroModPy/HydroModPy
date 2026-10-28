"""The size rules of the lake structures: cutoff walls, sills and the outlet disk.

Each cutoff wall is refined at the dam cell size in a zone of ``hfb_buffer``, or
twice the dam buffer. Two lakes apart get a sill zone finer than their gap,
buffered from simplified outlines, and touching lakes get none. The disk under
the dam goes when a wall zone already reaches it, unless the table forces it.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon, box

from hydromodpy.spatial.mesh.planning.lake_structures import (
    LakeStructure,
    lake_structures,
    sill_zone,
)
from hydromodpy.spatial.mesh.refinement_config import LakeRefinementConfig

_LAKE = Polygon([(0.0, 0.0), (1000.0, 0.0), (1000.0, 600.0), (0.0, 600.0)])
_OUTLET = Point(331315.0, 6781273.0)
_WALL_NEAR_THE_OUTLET = LineString([(331215.0, 6781273.0), (331255.0, 6781173.0)])
"""A wall 100 m from the outlet: its zone (260 m) and the disk (130 m) overlap by far."""
_WALL_FAR_FROM_THE_OUTLET = LineString([(329300.0, 6781273.0), (329400.0, 6781273.0)])
"""A wall on another lake 2 km away: the disk under the dam must stay."""


def _table(**overrides: object) -> LakeRefinementConfig:
    return LakeRefinementConfig(
        cell_size=80.0, buffer=160.0, dam_cell_size=60.0, dam_buffer=130.0, **overrides
    )


def _labels(wall: LineString, outlet: Point | None = _OUTLET, **overrides: object) -> set[str]:
    """The labels of the structures of one reservoir with its cutoff wall."""
    structures = lake_structures(
        {"reservoir": wall}, {"reservoir": _LAKE}, outlet, _table(**overrides)
    )
    return {structure.label for structure in structures}


def test_the_dam_disk_goes_when_the_wall_zone_reaches_the_outlet() -> None:
    labels = _labels(_WALL_NEAR_THE_OUTLET)

    assert "dam_outlet" not in labels
    assert "voile:reservoir" in labels


def test_the_dam_disk_stays_when_the_wall_is_far_from_the_outlet() -> None:
    assert "dam_outlet" in _labels(_WALL_FAR_FROM_THE_OUTLET)


def test_the_dam_disk_can_be_forced_next_to_a_wall() -> None:
    labels = _labels(_WALL_NEAR_THE_OUTLET, dam_outlet_disk=True)

    assert {"dam_outlet", "voile:reservoir"} <= labels


def test_the_dam_disk_can_be_switched_off_far_from_a_wall() -> None:
    assert _labels(_WALL_FAR_FROM_THE_OUTLET, dam_outlet_disk=False) == {"voile:reservoir"}


def test_the_dam_disk_is_a_point_the_planner_dilates_by_the_dam_buffer() -> None:
    table = _table()

    walls, lakes = {"reservoir": _WALL_FAR_FROM_THE_OUTLET}, {"reservoir": _LAKE}

    structures = {s.label: s for s in lake_structures(walls, lakes, _OUTLET, table)}

    outlet = structures["dam_outlet"]
    geometry, size, buffer = outlet.geometry, outlet.size_m, outlet.buffer_m
    assert (geometry.x, geometry.y) == (_OUTLET.x, _OUTLET.y)
    assert (size, buffer) == (table.dam_cell_size, table.dam_buffer)


def test_no_dam_disk_without_a_declared_outlet() -> None:
    assert _labels(_WALL_FAR_FROM_THE_OUTLET, outlet=None) == {"voile:reservoir"}


@pytest.mark.parametrize(("hfb_buffer", "width"), [(None, 260.0), (300.0, 300.0)])
def test_a_wall_zone_is_the_hfb_buffer_or_twice_the_dam_buffer(
    hfb_buffer: float | None, width: float
) -> None:
    structures = lake_structures(
        {"reservoir": _WALL_FAR_FROM_THE_OUTLET}, {}, None, _table(hfb_buffer=hfb_buffer)
    )

    assert structures == (
        LakeStructure("voile", "reservoir", _WALL_FAR_FROM_THE_OUTLET, 60.0, width),
    )


@pytest.mark.parametrize(("distance", "disk"), [(450.0, False), (450.5, True)])
def test_a_wall_reaches_the_disk_within_its_zone_width_plus_the_dam_buffer(
    distance: float, disk: bool
) -> None:
    """A zone of 320 m and a disk of 130 m touch when the wall is 450 m from the outlet."""
    wall = LineString([(0.0, 0.0), (0.0, 100.0)])
    table = _table(hfb_buffer=320.0)

    structures = lake_structures({"a": wall}, {}, Point(distance, 50.0), table)

    assert (structures[-1].label == "dam_outlet") is disk


def test_an_empty_wall_line_adds_no_zone() -> None:
    assert lake_structures({"a": LineString()}, {}, None, _table()) == ()


def _two_lakes(gap: float) -> dict[str, Polygon]:
    """Two square lakes *gap* metres apart, overlapping for a negative gap."""
    return {"a": box(0.0, 0.0, 400.0, 400.0), "b": box(400.0 + gap, 0.0, 800.0 + gap, 400.0)}


def test_two_lakes_apart_get_a_sill_zone_finer_than_their_gap() -> None:
    """A cell wider than the gap would straddle both lakes, and MF6 LAK takes one lake per cell."""
    gap = 40.0
    table = LakeRefinementConfig(dam_cell_size=60.0)

    structures = {s.label: s for s in lake_structures({}, _two_lakes(gap), None, table)}

    sill = structures["sill:a-b"]
    zone, size, margin = sill.geometry, sill.size_m, sill.buffer_m
    assert size < gap
    assert margin >= table.dam_cell_size
    assert zone.contains(box(400.0, 50.0, 400.0 + gap, 350.0))


@pytest.mark.parametrize(
    ("gap", "size", "margin"),
    [(100.0, 40.0, 150.0), (200.0, 60.0, 300.0), (5.0, 5.0, 60.0)],
    ids=["0.4 of the gap", "at most the dam cell size", "at least 5 m"],
)
def test_the_sill_size_and_margin_follow_the_gap(gap: float, size: float, margin: float) -> None:
    """The size is 0.4 of the gap within 5 m and the dam cell size, the margin 1.5 gaps."""
    table = LakeRefinementConfig(dam_cell_size=60.0)

    (sill,) = lake_structures({}, _two_lakes(gap), None, table)
    label, sill_size, sill_margin = sill.label, sill.size_m, sill.buffer_m

    assert (label, sill_size, sill_margin) == ("sill:a-b", size, margin)


@pytest.mark.parametrize("gap", [0.0, -50.0], ids=["touching", "overlapping"])
def test_touching_or_overlapping_lakes_get_no_sill_zone(gap: float) -> None:
    assert lake_structures({}, _two_lakes(gap), None, LakeRefinementConfig()) == ()


def test_an_empty_sill_zone_adds_no_structure() -> None:
    """A bump 0.1 m from the other lake goes with the simplification, and the zones miss."""
    bump = Polygon([(0, 0), (10, 0), (10, 4.9), (10.4, 5), (10, 5.1), (10, 10), (0, 10)])
    lakes = {"a": bump, "b": box(10.5, 0.0, 20.0, 10.0)}
    table = LakeRefinementConfig(dam_cell_size=0.1, dam_buffer=0.1)

    assert sill_zone(lakes["a"], lakes["b"], 0.15, sill_size=5.0).is_empty
    assert lake_structures({}, lakes, None, table) == ()


def test_the_structures_are_the_walls_then_each_pair_of_lakes_then_the_disk() -> None:
    lakes = {name: box(1000.0 * i, 0.0, 1000.0 * i + 900.0, 900.0) for i, name in enumerate("abc")}
    walls = {
        name: LineString([(1000.0 * i, 0.0), (1000.0 * i, 900.0)]) for i, name in enumerate("ac")
    }

    structures = lake_structures(walls, lakes, Point(5000.0, 5000.0), _table())

    assert [structure.label for structure in structures] == [
        "voile:a",
        "voile:c",
        "sill:a-b",
        "sill:a-c",
        "sill:b-c",
        "dam_outlet",
    ]


def test_no_structure_without_the_lake_table() -> None:
    assert lake_structures({"a": _WALL_NEAR_THE_OUTLET}, {"a": _LAKE}, _OUTLET, None) == ()


def _wiggly_lake(cx: float, n: int = 17000) -> Polygon:
    """A lake outline with *n* vertices and metre-scale noise, like a DEM-traced reservoir."""
    rng = np.random.default_rng(0)
    t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    r = 400.0 + 30.0 * np.sin(7.0 * t) + rng.uniform(-0.5, 0.5, n)
    return Polygon(np.column_stack([cx + r * np.cos(t), r * np.sin(t)]))


def test_the_sill_zone_of_simplified_outlines_matches_the_raw_buffer() -> None:
    """The outlines of two DEM-traced lakes are simplified first, C-07."""
    first, second = _wiggly_lake(0.0), _wiggly_lake(900.0)
    gap = first.distance(second)
    margin = max(1.5 * gap, 60.0)
    raw = first.buffer(margin).intersection(second.buffer(margin))
    sill_size = max(5.0, 0.4 * gap)

    zone = sill_zone(first, second, margin, sill_size=sill_size)

    # The outline moves by at most the tolerance, a tenth of the sill size, twice.
    assert zone.hausdorff_distance(raw) <= 0.2 * sill_size
