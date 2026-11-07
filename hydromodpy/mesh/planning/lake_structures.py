"""The size rules of the hydraulic structures of the lakes the mesh refines.

Each structure is a ``LakeStructure``, and the planner refines its geometry
dilated by its buffer at its cell size. There are three kinds, named by the
label of the structure.

- ``voile:<id>``, the cutoff wall line of lake ``<id>``, at ``dam_cell_size``. Its
  zone is ``hfb_buffer`` wide on each side, ``2 * dam_buffer`` without it, so it
  covers the lake outlet.
- ``sill:<a>-<b>``, the zone between two lakes apart. A cell wider than the gap
  would straddle both lakes, and MF6 LAK takes one lake per cell. So the sill
  size stays under the gap and the whole zone where the two lakes come close is
  refined, not only their nearest points. Touching or overlapping lakes get no
  sill, since no cell can separate them.
- ``dam_outlet``, the declared outlet, at ``dam_cell_size`` within
  ``dam_buffer``. It is left out when a wall zone already reaches the disk,
  unless ``dam_outlet_disk`` asks for it.

The workflow reads the walls, the lake footprints and the outlet from the run;
this module reads plain geometries only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from hydromodpy.mesh.refinement_config import LakeRefinementConfig

__all__ = [
    "MIN_SILL_SIZE_M",
    "SILL_MARGIN_PER_GAP",
    "SILL_SIZE_PER_GAP",
    "LakeStructure",
    "lake_structures",
    "sill_zone",
]

MIN_SILL_SIZE_M = 5.0
"""Smallest cell size of a sill, in meters."""

SILL_SIZE_PER_GAP = 0.4
"""Cell size of a sill as a share of the gap between the two lakes."""

SILL_MARGIN_PER_GAP = 1.5
"""Dilation of each lake for its sill zone, as a multiple of the gap, at least ``dam_cell_size``."""


@dataclass(frozen=True)
class LakeStructure:
    """A hydraulic structure of a lake that the mesh refines around.

    ``kind`` is ``voile`` (a cutoff wall), ``sill`` (the zone between two lakes) or
    ``dam_outlet``. ``name`` is the lake id of a wall, the pair ``<a>-<b>`` of a
    sill, and None for the outlet. The planner refines ``geometry`` dilated by
    ``buffer_m`` at ``size_m``.
    """

    kind: str
    name: str | None
    geometry: BaseGeometry
    size_m: float
    buffer_m: float

    @property
    def label(self) -> str:
        """``<kind>:<name>``, or the kind alone when the structure has no name."""
        return self.kind if self.name is None else f"{self.kind}:{self.name}"


def lake_structures(
    walls: Mapping[str, LineString],
    footprints: Mapping[str, Polygon],
    outlet: Point | None,
    lake_cfg: LakeRefinementConfig | None,
) -> tuple[LakeStructure, ...]:
    """The structures to refine, none without ``[mesh.lake_refinement]``.

    *walls* holds the cutoff wall line of each lake that has one and
    *footprints* the polygon of each lake, both by lake id in the order of the
    lake table. *outlet* is the declared outlet, None without one. The walls
    come first, then the sill of each pair of lakes, then the outlet disk.
    """
    if lake_cfg is None:
        return ()
    dam_cell_size = float(lake_cfg.dam_cell_size)
    dam_buffer = float(lake_cfg.dam_buffer)
    wall_width = float(lake_cfg.resolved_hfb_buffer)
    kept_walls = {lake_id: line for lake_id, line in walls.items() if not line.is_empty}
    structures: list[LakeStructure] = [
        LakeStructure("voile", f"{lake_id}", line, dam_cell_size, wall_width)
        for lake_id, line in kept_walls.items()
    ]
    for (first_id, first), (second_id, second) in combinations(footprints.items(), 2):
        gap = float(first.distance(second))
        if gap <= 0.0:
            continue
        sill_size = max(MIN_SILL_SIZE_M, min(dam_cell_size, SILL_SIZE_PER_GAP * gap))
        margin = max(SILL_MARGIN_PER_GAP * gap, dam_cell_size)
        zone = sill_zone(first, second, margin, sill_size=sill_size)
        if not zone.is_empty:
            structures.append(
                LakeStructure("sill", f"{first_id}-{second_id}", zone, sill_size, margin)
            )
    if outlet is not None:
        # The disk is redundant once a wall zone overlaps it.
        wall_reaches_the_outlet = any(
            float(line.distance(outlet)) <= wall_width + dam_buffer for line in kept_walls.values()
        )
        if lake_cfg.dam_outlet_disk is True or (
            lake_cfg.dam_outlet_disk is None and not wall_reaches_the_outlet
        ):
            structures.append(LakeStructure("dam_outlet", None, outlet, dam_cell_size, dam_buffer))
    return tuple(structures)


def sill_zone(
    first: BaseGeometry, second: BaseGeometry, margin: float, *, sill_size: float
) -> BaseGeometry:
    """The overlap of the two lakes dilated by *margin*, from simplified outlines.

    A DEM-traced reservoir holds some 17 000 vertices, and its raw buffer cost
    16 to 20 s per build. The outlines are simplified first at a tenth of the
    sill size, far below the cells placed there, so the zone moves by less than
    that tolerance.
    """
    tolerance = 0.1 * float(sill_size)
    dilated = [
        geometry.simplify(tolerance, preserve_topology=True).buffer(margin)
        for geometry in (first, second)
    ]
    zone = dilated[0].intersection(dilated[1])
    return zone.simplify(tolerance, preserve_topology=True)
