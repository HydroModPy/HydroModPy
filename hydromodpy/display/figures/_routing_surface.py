"""The surface the two routing diagnostics read, built once from a run's mesh.

Where the water goes, and where it stops going, are two readings of one object:
the persisted model top, a neighbour graph over the mesh faces, and the cell
every path is meant to end in. Building that object twice is how a map of the
flow directions comes to contradict the map of the depressions printed beside
it, so both figures build it here.

The neighbour graph is the same one
:func:`hydromodpy.core.stream_geometry.build_network_geometry` walks, and the
choice between shared edges and shared nodes is the one knob that changes it. A
flood conditioning a surface over one neighbourhood while a descent walks the
other leaves every filled cell spilling over a link the descent cannot take,
which is a defect this repository has already paid for once.

Water leaves this object through the edge of the active mesh, where the model
itself ends, and that is the only escape the surface has of its own. The outlet
is not one: it is the cell the stream criterion seals before measuring a
distance to it, a choice made about the catchment rather than a property of the
surface. A flood seeded on the mesh edge therefore raises the closed
depressions and nothing else, the outlet included when the outlet sits in one;
a flood seeded on the outlet alone must also raise every neighbouring basin,
which drains perfectly well and simply not here.

Nothing here decides anything a solver decided: the elevations come from the
run, and the outlet is the low point of the delineated catchment, or of the
active mesh when the run carries no catchment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.field_routing import (
    DownhillGraph,
    active_surface_mask,
    build_downhill_graph,
    cell_adjacency_from_face_connectivity,
    cell_centroids_from_mesh,
    domain_edge_cells,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.core.topographic_distance import shared_node_adjacency

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

logger = get_logger(__name__)

_WATERSHED_FEATURE = "watershed"
"""The delineated catchment, under the name the geographic step persists it."""

_MISSING_FEATURE = (KeyError, ValueError, FileNotFoundError, RuntimeError)
"""What a run raises when a mesh or a feature it never wrote is asked for.

``AttributeError`` is deliberately not in it: a run that answers neither
``mesh`` nor ``geographic`` is a coding error on the caller's side, and
swallowing it here would turn it into a silently degraded figure.
"""


@dataclass(frozen=True, slots=True)
class RoutingSurface:
    """The mesh top, the graph over it, and the cell every path ends in."""

    topography: np.ndarray
    """(n_cells,) persisted model top, in metres."""

    centroids: np.ndarray
    """(n_cells, 2) face centres, the points a direction is measured between."""

    adjacency: list[set[int]]
    """Neighbour indices per cell: shared edges, or shared nodes with diagonals."""

    face_node_connectivity: np.ndarray
    """(n_cells, n_nodes) UGRID face definition the graph was built over."""

    vertices: np.ndarray
    """(n_nodes, 2+) mesh nodes, what an edge length is measured between."""

    active: np.ndarray
    """(n_cells,) bool: cells carrying a finite, non-nodata elevation."""

    catchment: np.ndarray | None
    """(n_cells,) bool: the delineated catchment, None when the run has none."""

    domain_edge: np.ndarray
    """(n_cells,) bool: active cells holding a face edge no active cell shares.

    The geometric boundary of the modelled domain, where water leaves the mesh.
    It does not move with ``diagonal_neighbors``: whichever links the descent
    is allowed to take, it leaves through the same faces.
    """

    outlet: int
    """The cell water leaves through: the low point of the support above."""

    diagonal_neighbors: bool

    @property
    def n_cells(self) -> int:
        """Number of mesh faces."""
        return int(self.topography.size)

    @property
    def neighbourhood_note(self) -> str:
        """The line naming the graph both the flood and the descent walk."""
        if self.diagonal_neighbors:
            return "neighbourhood: shared nodes, the eight D8 links including the diagonals"
        return "neighbourhood: shared edges, the four cardinal links and no diagonal"

    @property
    def support_name(self) -> str:
        """The name of the support the outlet was resolved over."""
        return "the delineated catchment" if self.catchment is not None else "the active mesh"

    @property
    def outlet_note(self) -> str:
        """The line naming the cell the answer depends on."""
        return (
            f"outlet cell {self.outlet} at {self.topography[self.outlet]:.2f} m, "
            f"lowest of {self.support_name}"
        )

    @property
    def escape_note(self) -> str:
        """The line naming every cell water may leave the domain through."""
        return (
            f"seeded on every escape: {int(self.domain_edge.sum())} cells on the edge of "
            "the active mesh, the outlet excluded"
        )

    def outlet_mask(self) -> np.ndarray:
        """Return the seed mask holding the outlet alone."""
        mask = np.zeros(self.n_cells, dtype=bool)
        mask[self.outlet] = True
        return mask

    def escape_mask(self) -> np.ndarray:
        """Return the seed mask of every cell water can leave the domain through.

        The edge of the active mesh, and nothing else. The outlet is left out
        on purpose: sealing a cell does not make the surface drain through it,
        and seeding it hides the depression the outlet may itself sit in.
        Measured on nancon_diagnostic.v2, where the outlet is cell 49905 at
        106.42 m and interior to the mesh: adding it as a seed dropped fifteen
        cells from the answer, its own among them, and that one needs 4.07 m of
        fill before it spills to the edge of the domain.
        """
        return self.domain_edge.copy()

    def downhill_graph(self) -> DownhillGraph:
        """Return the steepest-descent receiver graph over this surface.

        The drop is normalised by the centre-to-centre distance, so a diagonal
        link does not win on a longer segment alone.
        """
        return build_downhill_graph(
            self.topography,
            self.face_node_connectivity,
            centroids=self.centroids,
            inactive_mask=~self.active,
            adjacency=self.adjacency,
        )

    def within_catchment(self, mask: np.ndarray) -> np.ndarray:
        """Restrict ``mask`` to the catchment, or leave it alone without one."""
        selected = np.asarray(mask, dtype=bool).reshape(-1)
        return selected if self.catchment is None else selected & self.catchment


def unavailable_reason_for_routing(sim: Run) -> str | None:
    """Return why this run carries no surface to route on, or ``None``.

    Answered before rendering so a gallery skips the figure with a sentence
    rather than failing halfway through a graph build.
    """
    try:
        mesh = sim.mesh
    except _MISSING_FEATURE as exc:
        return f"run carries no mesh to route on ({type(exc).__name__})"
    if mesh is None or mesh.topography is None:
        return "run persisted no mesh topography to route on"
    topography = np.asarray(mesh.topography, dtype=float).reshape(-1)
    if topography.size == 0 or not active_surface_mask(topography).any():
        return "the persisted mesh top holds no cell with a usable elevation"
    return None


def routing_surface_from_run(sim: Run, *, diagonal_neighbors: bool = False) -> RoutingSurface:
    """Build the routing surface of one run from its own mesh.

    ``diagonal_neighbors`` picks the neighbour graph, the same knob the stream
    criterion carries: shared edges by default, shared nodes to recover the
    diagonal descents of a structured grid.
    """
    reason = unavailable_reason_for_routing(sim)
    if reason is not None:
        raise ValueError(f"routing surface unavailable for {sim.sim_id}: {reason}")

    mesh = sim.mesh
    topography = np.asarray(mesh.topography, dtype=float).reshape(-1)
    connectivity = np.asarray(mesh.face_node_connectivity)
    n_cells = int(topography.size)
    if connectivity.shape[0] != n_cells:
        raise ValueError(
            f"the mesh top holds {n_cells} cells and the connectivity {connectivity.shape[0]} "
            "faces; they were not written for the same run."
        )
    vertices = np.asarray(mesh.vertices, dtype=float)
    centroids = cell_centroids_from_mesh(vertices, connectivity)
    adjacency = (
        shared_node_adjacency(connectivity, n_cells=n_cells)
        if diagonal_neighbors
        else cell_adjacency_from_face_connectivity(connectivity, n_cells=n_cells)
    )
    active = active_surface_mask(topography)
    catchment = _catchment_cells(sim, centroids, active, mesh.crs)
    return RoutingSurface(
        topography=topography,
        centroids=centroids,
        adjacency=adjacency,
        face_node_connectivity=connectivity,
        vertices=vertices,
        active=active,
        catchment=catchment,
        domain_edge=domain_edge_cells(connectivity, active),
        outlet=_lowest_cell(topography, active if catchment is None else catchment),
        diagonal_neighbors=bool(diagonal_neighbors),
    )


def _lowest_cell(topography: np.ndarray, within: np.ndarray) -> int:
    """Return the lowest cell of a support, the way the stream criterion does."""
    return int(np.argmin(np.where(within, topography, np.inf)))


def _catchment_cells(
    sim: Run,
    centroids: np.ndarray,
    active: np.ndarray,
    mesh_crs: str | None,
) -> np.ndarray | None:
    """Return the active cells whose centre falls in the delineated catchment.

    ``None`` when the run carries none, which is legitimate on a synthetic
    domain and moves the outlet to the low point of the whole active mesh. On a
    real surface the two answers differ, so the figures name the support they
    used rather than leaving it implied.
    """
    from shapely import contains_xy
    from shapely.ops import unary_union

    try:
        watershed = sim.geographic(_WATERSHED_FEATURE)
    except _MISSING_FEATURE as exc:
        logger.warning(
            "Routing surface: run %s carries no delineated catchment (%s). Falling back to "
            "the low point of the whole active mesh, which on a buffered box is not the "
            "outlet of the catchment: the figures then measure the mesh, not the basin. "
            "Check that the geographic step ran for this run.",
            sim.sim_id,
            type(exc).__name__,
        )
        return None
    if watershed is None or watershed.empty:
        logger.warning(
            "Routing surface: the delineated catchment of run %s is an empty feature. "
            "Falling back to the low point of the whole active mesh, which on a buffered "
            "box is not the outlet of the catchment.",
            sim.sim_id,
        )
        return None
    if mesh_crs and watershed.crs is not None and str(watershed.crs) != str(mesh_crs):
        watershed = watershed.to_crs(mesh_crs)
    inside = np.asarray(
        contains_xy(unary_union(list(watershed.geometry)), centroids[:, 0], centroids[:, 1]),
        dtype=bool,
    )
    inside &= active
    if not inside.any():
        logger.warning(
            "Routing surface: the delineated catchment of run %s projects onto no active "
            "cell of the mesh. Check the CRS the watershed was written in. Falling back to "
            "the low point of the whole active mesh.",
            sim.sim_id,
        )
        return None
    return inside


__all__ = (
    "RoutingSurface",
    "routing_surface_from_run",
    "unavailable_reason_for_routing",
)
