"""Grid-based spatial indexing helpers for local refinement policies.

The grid is deliberately simple: it is not a replacement for Shapely or STRtree.
Its only job is to answer "which refinement curves are plausible neighbors in
this part of the domain?" so the policy can avoid near-global pairwise scans.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import floor
from typing import Protocol

from shapely.geometry.base import BaseGeometry


class RefinementCurveLike(Protocol):
    """Minimal curve contract consumed by the locality grid helpers."""

    curve_tag: int
    family: str
    geometry: BaseGeometry


@dataclass(frozen=True, order=True)
class RefinementGridCellId:
    """One stable row/column identifier inside the locality grid."""

    row: int
    col: int


@dataclass(frozen=True)
class RefinementCurveFootprint:
    """BBox-based footprint of one candidate curve on the locality grid."""

    curve_tag: int
    family: str
    bounds: tuple[float, float, float, float]
    cell_ids: tuple[RefinementGridCellId, ...]


@dataclass(frozen=True)
class RefinementGrid:
    """Regular grid used to localize refinement diagnostics.

    The grid stores two complementary views:

    - cell -> curve tags, to query a local neighborhood quickly
    - curve tag -> cell footprint, to explain afterwards why a curve was seen
      in a given neighborhood
    """

    bounds: tuple[float, float, float, float]
    cell_size: float
    row_count: int
    col_count: int
    active_cell_ids: tuple[RefinementGridCellId, ...]
    cell_curve_tags: Mapping[RefinementGridCellId, tuple[int, ...]]
    curve_footprints: Mapping[int, RefinementCurveFootprint]

    def iter_neighborhood_cell_ids(
        self,
        cell_id: RefinementGridCellId,
        *,
        rings: int = 1,
    ) -> tuple[RefinementGridCellId, ...]:
        """Return one Moore neighborhood clipped to grid bounds."""
        if rings < 0:
            raise ValueError("rings must be >= 0")
        cell_ids: list[RefinementGridCellId] = []
        row_min = max(0, int(cell_id.row) - int(rings))
        row_max = min(int(self.row_count) - 1, int(cell_id.row) + int(rings))
        col_min = max(0, int(cell_id.col) - int(rings))
        col_max = min(int(self.col_count) - 1, int(cell_id.col) + int(rings))
        for row in range(row_min, row_max + 1):
            for col in range(col_min, col_max + 1):
                cell_ids.append(RefinementGridCellId(row=row, col=col))
        return tuple(cell_ids)

    def collect_neighborhood_curve_tags(
        self,
        cell_id: RefinementGridCellId,
        *,
        rings: int = 1,
    ) -> tuple[int, ...]:
        """Return deduplicated curve tags active in one local neighborhood."""
        curve_tags: set[int] = set()
        for neighbor_id in self.iter_neighborhood_cell_ids(cell_id, rings=rings):
            curve_tags.update(self.cell_curve_tags.get(neighbor_id, ()))
        return tuple(sorted(int(curve_tag) for curve_tag in curve_tags))


def build_refinement_grid(
    *,
    candidates: Sequence[RefinementCurveLike],
    cell_size: float,
) -> RefinementGrid:
    """Index candidate curves in one regular bbox grid.

    The indexing is bbox-based on purpose. It is conservative, cheap to build,
    and sufficient for the hotspot preselection stage.
    """
    if cell_size <= 0.0:
        raise ValueError("cell_size must be > 0")

    if not candidates:
        return RefinementGrid(
            bounds=(0.0, 0.0, 0.0, 0.0),
            cell_size=float(cell_size),
            row_count=0,
            col_count=0,
            active_cell_ids=(),
            cell_curve_tags={},
            curve_footprints={},
        )

    xmin = min(float(candidate.geometry.bounds[0]) for candidate in candidates)
    ymin = min(float(candidate.geometry.bounds[1]) for candidate in candidates)
    xmax = max(float(candidate.geometry.bounds[2]) for candidate in candidates)
    ymax = max(float(candidate.geometry.bounds[3]) for candidate in candidates)

    col_count = int(floor((xmax - xmin) / float(cell_size))) + 1
    row_count = int(floor((ymax - ymin) / float(cell_size))) + 1

    cell_curve_tags_raw: dict[RefinementGridCellId, list[int]] = defaultdict(list)
    curve_footprints: dict[int, RefinementCurveFootprint] = {}

    for candidate in candidates:
        curve_tag = int(candidate.curve_tag)
        bounds = tuple(float(value) for value in candidate.geometry.bounds)
        touched_cell_ids = _cell_ids_for_bounds(
            bounds=bounds,
            grid_bounds=(xmin, ymin, xmax, ymax),
            cell_size=float(cell_size),
            row_count=row_count,
            col_count=col_count,
        )
        for cell_id in touched_cell_ids:
            cell_curve_tags_raw[cell_id].append(curve_tag)
        curve_footprints[curve_tag] = RefinementCurveFootprint(
            curve_tag=curve_tag,
            family=str(candidate.family),
            bounds=bounds,
            cell_ids=touched_cell_ids,
        )

    return RefinementGrid(
        bounds=(float(xmin), float(ymin), float(xmax), float(ymax)),
        cell_size=float(cell_size),
        row_count=int(row_count),
        col_count=int(col_count),
        active_cell_ids=tuple(sorted(cell_curve_tags_raw.keys())),
        cell_curve_tags={
            cell_id: tuple(sorted(set(int(curve_tag) for curve_tag in curve_tags)))
            for cell_id, curve_tags in sorted(cell_curve_tags_raw.items())
        },
        curve_footprints=curve_footprints,
    )


def _cell_ids_for_bounds(
    *,
    bounds: tuple[float, float, float, float],
    grid_bounds: tuple[float, float, float, float],
    cell_size: float,
    row_count: int,
    col_count: int,
) -> tuple[RefinementGridCellId, ...]:
    """Return one conservative set of grid cells touched by one bbox."""
    xmin, ymin, xmax, ymax = bounds
    grid_xmin, grid_ymin, _grid_xmax, _grid_ymax = grid_bounds
    col_start = _cell_index(xmin, origin=grid_xmin, cell_size=cell_size)
    col_end = _cell_index(xmax, origin=grid_xmin, cell_size=cell_size)
    row_start = _cell_index(ymin, origin=grid_ymin, cell_size=cell_size)
    row_end = _cell_index(ymax, origin=grid_ymin, cell_size=cell_size)

    cell_ids: list[RefinementGridCellId] = []
    for row in range(max(0, row_start), min(row_count - 1, row_end) + 1):
        for col in range(max(0, col_start), min(col_count - 1, col_end) + 1):
            cell_ids.append(RefinementGridCellId(row=row, col=col))
    return tuple(cell_ids)


def _cell_index(
    coordinate: float,
    *,
    origin: float,
    cell_size: float,
) -> int:
    """Return one integer grid index for one coordinate."""
    return int(floor((float(coordinate) - float(origin)) / float(cell_size)))


__all__ = [
    "build_refinement_grid",
    "RefinementCurveFootprint",
    "RefinementCurveLike",
    "RefinementGrid",
    "RefinementGridCellId",
]
