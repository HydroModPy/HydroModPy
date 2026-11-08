"""Route a per-cell release downstream on a receiver graph, to get a discharge anywhere.

``discharge`` on ``support="domain"`` sums the release of the whole catchment and
answers for the outlet alone. A gauge that is not at the outlet closes a smaller
catchment and cannot be compared to that sum, so scoring it needs the discharge
AT ITS OWN CELL.

The quantity routed here is the per-cell release that the union of packages
already reports: DRN, the drain flux handed to the mover, SFR, LAK and a
stream-role CHD. That union is what makes this package-agnostic. Every one of
those records is a flux ACROSS THE AQUIFER FACE, counted once where it crosses,
so summing them upstream of a cell is the water that reached the surface
network above it, whatever package carried it.

At the outlet cell the upstream set is the whole catchment and the routed value
is the domain sum, by construction. That identity is the contract: a per-cell
discharge that does not reproduce the domain series at the outlet is wrong, and
``tests/unit/catchment/drainage/test_routing.py`` checks it.

What this does NOT model is the routing the surface network performs on its own:
channel storage, diversions, evaporation from a reach or a lake. It sums what
entered the network upstream. Under SFR, MODFLOW itself routes the water and its
per-reach ``downstream_flow`` is the faithful quantity. This module is what
every backend and every package combination can answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from hydromodpy.catchment.drainage.graph import accumulate_on_downhill_graph
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

_FAR_FROM_ONE = 0.90
"""Below this, the graph and the delineated catchment describe different
drainage. Matches ``alpha_warning_threshold``, the network criterion's own
cutoff for a catchment-restricted agreement ratio. Fixed rather than a config
``Field``: this ratio is a property of the mesh and the delineation, never of
a calibrated parameter, so no trial could give a reason to move it."""


@dataclass(frozen=True, slots=True, eq=False)
class UpstreamArea:
    """The area each cell drains and how much of its catchment the graph can drain.

    ``m2`` is the area drained by each cell, in m2. ``largest_drainable_share``
    is the largest of them over the area of the catchment, or ``None`` for a
    catchment of no area. It is one when the graph drains the catchment.
    """

    m2: np.ndarray
    largest_drainable_share: float | None


def route_release_to_discharge(
    release: np.ndarray,
    graph: Any,
    *,
    catchment_mask: np.ndarray,
) -> np.ndarray:
    """Accumulate a per-cell release downstream and return it per cell.

    ``release`` is ``(n_times, n_cells)`` or ``(n_cells,)`` in m3/s per cell, the
    frame ``release_flux`` already serves. ``catchment_mask`` zeroes the cells
    outside the catchment, the basin of D the build kept, before routing: the
    mesh is built on a buffered box, and the neighboring basins drain into it.
    Measured on the Nancon at 25 m, the unmasked domain carries 2.4 times the
    water the gauge sees.
    """
    values = np.asarray(release, dtype=float)
    single = values.ndim == 1
    stack = values.reshape(1, -1) if single else values
    mask = np.asarray(catchment_mask, dtype=bool).reshape(-1)
    if mask.size != stack.shape[1]:
        raise ValueError(
            f"the catchment mask holds {mask.size} cells and the release {stack.shape[1]}."
        )
    if not mask.any():
        raise ValueError("the catchment mask of a per-cell discharge holds no cell.")

    inside = np.where(mask[None, :], np.nan_to_num(stack, nan=0.0), 0.0)
    accumulated = accumulate_on_downhill_graph(graph, inside)
    accumulated = np.nan_to_num(accumulated, nan=0.0)
    return accumulated[0] if single else accumulated


def upstream_area(
    cell_area_m2: np.ndarray, graph: Any, *, catchment_mask: np.ndarray
) -> UpstreamArea:
    """Return the catchment area drained by each cell, in m2, with the drainable share.

    Accumulating the cell areas on the same graph as the release is what keeps
    the two consistent: the runoff a gauge sees is the runoff over exactly the
    cells whose release it also sees.

    The largest accumulation is stated against the catchment it should equal.
    The catchment is the basin of D, the cells that drain through the outlet on
    the very graph this routes on, so the accumulation at the outlet is the area
    of the basin and the ratio is one by construction. It is far below one only
    for a mask that is not that basin: the old support of a model that carries
    no basin of D, a catchment polygon cut across the talweg the mesh top
    carries. Then the graph the model routes on and the delineation describe
    different drainage, and every routed quantity read from it is a fraction of
    what it claims.
    """
    areas = np.asarray(cell_area_m2, dtype=float).reshape(-1)
    accumulated = route_release_to_discharge(areas, graph, catchment_mask=catchment_mask)
    return UpstreamArea(
        m2=accumulated,
        largest_drainable_share=largest_drainable_share(areas, accumulated, catchment_mask),
    )


def largest_drainable_share(
    areas: np.ndarray, accumulated: np.ndarray, catchment_mask: np.ndarray
) -> float | None:
    """State the largest accumulation against the catchment it should equal.

    Warns, once per call, when the ratio is far from one: a graph that cannot
    drain the delineated basin makes an accumulated discharge read at any of
    its cells meaningless, which is why this repository refuses to locate a
    gauge by coordinate rather than score it. The ratio never penalizes a
    trial's cost, because it does not depend on one.
    """
    mask = np.asarray(catchment_mask, dtype=bool).reshape(-1)
    catchment_m2 = float(areas[mask].sum()) if mask.any() else 0.0
    largest_m2 = float(np.nanmax(accumulated)) if accumulated.size else 0.0
    if catchment_m2 <= 0.0:
        return None
    ratio = largest_m2 / catchment_m2
    if ratio < _FAR_FROM_ONE:
        logger.warning(
            "Routing graph: the most accumulated cell drains %.3f km2 of the %.3f km2 "
            "catchment (%.1f%%). One means the graph drains the basin; far below it, this "
            "graph and the delineation describe different drainage, so an accumulated "
            "discharge read at any of its cells is meaningless, which is why a gauge "
            "located by coordinate is refused rather than scored.",
            largest_m2 / 1e6,
            catchment_m2 / 1e6,
            100.0 * ratio,
        )
    return ratio
