"""Raise closed depressions of a surface until every path reaches an outlet.

A downslope distance is a length measured along a flow path, and a flow path is
only defined once the depressions are resolved: on a raw surface a descent stops
in a pit that does not exist hydrologically, and the cells behind it have no
distance at all.

Conditioning a raster before delineation does not help a criterion that measures
on a mesh. The result is pit-free **on the raster's own grid**; resampled onto a
mesh with a different neighborhood it grows new pits. The surface has to be
conditioned on the graph the distances are measured on, which is what this does.

The algorithm is the priority flood of Barnes, Lehman and Mulla (2014), written
over an explicit neighbor list instead of a raster so it applies to a mesh of
any cell arity. Water is walked inwards from the outlets, always through the
lowest reachable rim, and any cell below the level of that rim is raised onto it.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = ("DepressionFillReport", "fill_depressions_on_graph", "priority_flood")

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


def priority_flood(
    values: Any,
    adjacency: list[set[int]],
    seeds: Any,
    *,
    step: Any,
    pin: np.ndarray | None = None,
    tolerance: float = 0.0,
    every_cell: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Flood ``values`` from the seeds, always through the lowest rim, and return it with the raised cells.

    The one flood of the package: :func:`fill_depressions_on_graph` and the
    descent of :mod:`hydromodpy.catchment.drainage.descent` both call it.

    Parameters
    ----------
    values
        One elevation per cell. A non-finite value marks an inactive cell: it is
        never raised and never crossed. Seeds must be finite cells.
    adjacency
        Neighbor indices per cell.
    seeds
        Boolean mask of the cells the flood starts from.
    step
        Slope added above the rim, a number or one value per cell, taken at the
        cell that is raised.
    pin
        One receiver per cell, ``-1`` for none. A pinned cell is entered from its
        pin only, and every pinned cell is also reached from its pin.
    tolerance
        A cell within ``tolerance`` above the level is raised like a cell below it.
    every_cell
        Raise ``ValueError`` when a finite cell is never reached from a seed.

    Returns
    -------
    surface, raised
        The flooded copy and the mask of the cells set to ``level + step``.
    """
    surface = np.array(values, dtype="float64").reshape(-1)
    n_cells = surface.size
    visited = ~np.isfinite(surface)
    raised = np.zeros(n_cells, dtype=bool)
    rise = np.broadcast_to(np.asarray(step, dtype="float64"), surface.shape)
    donors: dict[int, list[int]] = {}
    if pin is not None:
        for cell in np.flatnonzero(pin >= 0).tolist():
            donors.setdefault(int(pin[cell]), []).append(cell)

    frontier: list[tuple[float, int]] = []
    for cell in np.flatnonzero(np.asarray(seeds, dtype=bool).reshape(-1)).tolist():
        visited[cell] = True
        heapq.heappush(frontier, (float(surface[cell]), cell))
    while frontier:
        level, cell = heapq.heappop(frontier)
        neighbours = adjacency[cell]
        if donors and cell in donors:
            neighbours = [*neighbours, *donors[cell]]
        for neighbour in neighbours:
            if visited[neighbour]:
                continue
            if pin is not None and pin[neighbour] >= 0 and pin[neighbour] != cell:
                continue
            visited[neighbour] = True
            if surface[neighbour] <= level + tolerance:
                surface[neighbour] = level + rise[neighbour]
                raised[neighbour] = True
            heapq.heappush(frontier, (float(surface[neighbour]), neighbour))

    if every_cell:
        unreached = np.flatnonzero(~visited)
        if unreached.size:
            raise ValueError(
                f"{unreached.size} cell(s) are never reached from a seed "
                f"(first: {int(unreached[0])}): the pinned cells around them are entered "
                "only from pins that lie beyond them."
            )
    return surface, raised


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
        Neighbor indices per cell, the same graph the distances are measured on.
    outlets
        Boolean mask of the cells water may leave through. The standard form
        seeds the whole border of the domain (``domain_edge_cells``), where
        water leaves the model. Seeding a single interior cell instead declares
        the domain endorheic towards it, and a valley that drains off the
        domain is raised until it spills across a divide. Seeding nothing
        raises every cell of the surface, which is why an empty mask is refused.
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
    surface, _ = priority_flood(surface, adjacency, seeds, step=epsilon)

    raised = finite & (surface > original + epsilon / 2.0)
    return DepressionFillReport(
        surface=surface,
        n_filled=int(np.count_nonzero(raised)),
        max_fill=float(np.max(surface[raised] - original[raised])) if np.any(raised) else 0.0,
    )
