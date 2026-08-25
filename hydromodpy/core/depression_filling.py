"""Raise closed depressions of a surface until every path reaches an outlet.

A downslope distance is a length measured along a flow path, and a flow path is
only defined once the depressions are resolved: on a raw surface a descent stops
in a pit that does not exist hydrologically, and the cells behind it have no
distance at all.

Conditioning a raster before delineation does not help a criterion that measures
on a mesh. The result is pit-free **on the raster's own grid**; resampled onto a
mesh with a different neighbourhood it grows new pits. The surface has to be
conditioned on the graph the distances are measured on, which is what this does.

The algorithm is the priority flood of Barnes, Lehman and Mulla (2014), written
over an explicit neighbour list instead of a raster so it applies to a mesh of
any cell arity. Water is walked inwards from the outlets, always through the
lowest reachable rim, and any cell below the level of that rim is raised onto it.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = ("DepressionFillReport", "fill_depressions_on_graph")

#: Slope added at each step inside a filled depression, in the unit of the
#: surface. It keeps the filled floor draining instead of flat, which a
#: steepest-descent receiver graph needs to leave it at all.
DEFAULT_EPSILON_M = 1.0e-3


@dataclass(frozen=True, slots=True)
class DepressionFillReport:
    """What the flood had to change to make every path reach an outlet."""

    surface: np.ndarray
    n_filled: int
    max_fill: float

    @property
    def filled_fraction(self) -> float:
        """Share of the surface that was raised."""
        return float(self.n_filled) / float(self.surface.size) if self.surface.size else 0.0


def fill_depressions_on_graph(
    values: Any,
    adjacency: list[set[int]],
    outlets: Any,
    *,
    epsilon: float = DEFAULT_EPSILON_M,
) -> DepressionFillReport:
    """Return ``values`` with every closed depression raised to its spill level.

    Parameters
    ----------
    values
        One elevation per cell. A non-finite value marks an inactive cell: it is
        never raised and never crossed.
    adjacency
        Neighbour indices per cell, the same graph the distances are measured on.
    outlets
        Boolean mask of the cells water may leave through. Seeding it with the
        low point of the catchment is enough; seeding it with nothing raises
        every cell of the surface, which is why an empty mask is refused.
    epsilon
        Slope added per step inside a filled depression.

    Raises
    ------
    ValueError
        When no outlet is declared, or none of them is a finite cell.
    """
    surface = np.array(values, dtype="float64").reshape(-1)
    finite = np.isfinite(surface)
    seeds = np.asarray(outlets, dtype=bool).reshape(-1)
    if seeds.size != surface.size:
        raise ValueError(f"the outlet mask holds {seeds.size} cells, the surface {surface.size}.")
    seeds = seeds & finite
    if not np.any(seeds):
        raise ValueError(
            "no finite outlet to flood from: every cell would be raised to the highest "
            "rim of the surface."
        )
    if len(adjacency) != surface.size:
        raise ValueError(f"the adjacency holds {len(adjacency)} cells, the surface {surface.size}.")

    original = surface.copy()
    visited = np.zeros(surface.size, dtype=bool)
    frontier: list[tuple[float, int]] = []
    for cell in np.flatnonzero(seeds):
        index = int(cell)
        visited[index] = True
        heapq.heappush(frontier, (surface[index], index))

    while frontier:
        level, cell = heapq.heappop(frontier)
        for neighbour in adjacency[cell]:
            if visited[neighbour] or not finite[neighbour]:
                continue
            visited[neighbour] = True
            if surface[neighbour] <= level:
                surface[neighbour] = level + epsilon
            heapq.heappush(frontier, (surface[neighbour], neighbour))

    raised = finite & (surface > original + epsilon / 2.0)
    return DepressionFillReport(
        surface=surface,
        n_filled=int(np.count_nonzero(raised)),
        max_fill=float(np.max(surface[raised] - original[raised])) if np.any(raised) else 0.0,
    )
