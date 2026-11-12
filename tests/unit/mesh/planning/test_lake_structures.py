"""The size rules of the lake structures: cutoff walls, sills and the outlet disk.

Each cutoff wall is refined at the dam cell size in a zone of ``hfb_buffer``, or
twice the dam buffer. Two lakes apart get a sill zone finer than their gap,
buffered from simplified outlines, and touching lakes get none. The disk under
the dam goes when a wall zone already reaches it, unless the table forces it.
"""

from __future__ import annotations

import pytest
from shapely.geometry import LineString, Point, Polygon, box

from hydromodpy.mesh.planning.lake_structures import lake_structures, sill_zone
from hydromodpy.mesh.refinement_config import LakeRefinementConfig

_LAKE = box(0.0, 0.0, 1000.0, 600.0)
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
    structures = lake_structures(
        {"reservoir": wall}, {"reservoir": _LAKE}, outlet, _table(**overrides)
    )
    return {structure.label for structure in structures}


# Labels of the structures of one reservoir with its cutoff wall.
DISK_CASES = [
    pytest.param(
        _WALL_NEAR_THE_OUTLET,
        {},
        {"voile:reservoir"},
        {"dam_outlet"},
        id="wall zone reaches the outlet",
    ),
    pytest.param(
        _WALL_FAR_FROM_THE_OUTLET,
        {},
        {"dam_outlet", "voile:reservoir"},
        set(),
        id="wall far from the outlet",
    ),
    pytest.param(
        _WALL_NEAR_THE_OUTLET,
        {"dam_outlet_disk": True},
        {"dam_outlet", "voile:reservoir"},
        set(),
        id="disk forced next to a wall",
    ),
    pytest.param(
        _WALL_FAR_FROM_THE_OUTLET,
        {"dam_outlet_disk": False},
        {"voile:reservoir"},
        {"dam_outlet"},
        id="disk switched off far from a wall",
    ),
]


@pytest.mark.parametrize(("wall", "overrides", "present", "absent"), DISK_CASES)
def test_dam_disk(wall, overrides, present, absent) -> None:
    labels = _labels(wall, **overrides)

    assert present <= labels
    assert not absent & labels


def test_dam_disk_geometry() -> None:
    table = _table()
    walls, lakes = {"reservoir": _WALL_FAR_FROM_THE_OUTLET}, {"reservoir": _LAKE}

    structures = {s.label: s for s in lake_structures(walls, lakes, _OUTLET, table)}

    outlet = structures["dam_outlet"]
    assert (outlet.geometry.x, outlet.geometry.y) == (_OUTLET.x, _OUTLET.y)
    assert (outlet.size_m, outlet.buffer_m) == (table.dam_cell_size, table.dam_buffer)


def _two_lakes(gap: float) -> dict[str, Polygon]:
    """Two square lakes *gap* meters apart, overlapping for a negative gap."""
    return {"a": box(0.0, 0.0, 400.0, 400.0), "b": box(400.0 + gap, 0.0, 800.0 + gap, 400.0)}


def test_sill_zone_between_lakes() -> None:
    # A cell wider than the gap would straddle both lakes, and MF6 LAK takes one lake per cell.
    gap = 40.0
    table = LakeRefinementConfig(dam_cell_size=60.0)

    structures = {s.label: s for s in lake_structures({}, _two_lakes(gap), None, table)}

    sill = structures["sill:a-b"]
    zone, size, margin = sill.geometry, sill.size_m, sill.buffer_m
    assert size < gap
    assert margin >= table.dam_cell_size
    assert zone.contains(box(400.0, 50.0, 400.0 + gap, 350.0))


@pytest.mark.parametrize("gap", [0.0, -50.0], ids=["touching", "overlapping"])
def test_no_sill_for_touching_lakes(gap: float) -> None:
    assert lake_structures({}, _two_lakes(gap), None, LakeRefinementConfig()) == ()


def test_empty_sill_zone() -> None:
    # A bump 0.1 m from the other lake goes with the simplification, and the zones miss.
    bump = Polygon([(0, 0), (10, 0), (10, 4.9), (10.4, 5), (10, 5.1), (10, 10), (0, 10)])
    lakes = {"a": bump, "b": box(10.5, 0.0, 20.0, 10.0)}
    table = LakeRefinementConfig(dam_cell_size=0.1, dam_buffer=0.1)

    assert sill_zone(lakes["a"], lakes["b"], 0.15, sill_size=5.0).is_empty
    assert lake_structures({}, lakes, None, table) == ()
