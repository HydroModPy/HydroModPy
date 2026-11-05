"""The descent D: where water goes on the model top, as a computation only.

Routing needs a surface on which every cell drains. The model top T is not one:
projected onto a mesh it holds pits the routing DEM never had, and raising T
until it drains would change the ground the solver sees. D resolves this on a
COPY of T (principle P2 of the network architecture): the copy is filled so each
cell holds a descending path to a base level, and it never returns to the solver.
The channel bed, the drain elevations and the reach tops keep reading T.

The fill runs on the very graph that is descended. A flood only guarantees a
strictly lower neighbor among the cells it walked, so a fill on one
neighborhood and a descent on another leave filled cells spilling over a link
the descent cannot take (see the comment in
:func:`hydromodpy.core.stream.geometry.build_network_geometry`). D floods like
the stream criterion's fill, with four differences: its seeds include the
constant-head cells the caller declares, its lakes are traversed, its channel
cells follow the channel tree A by pinned receivers (principle P3), and a cell a
hair above the flood level is raised too, so the receiver graph never meets a
drop below its own tolerance.

A lake is traversed, never a seed. Its cells keep their value of T and are
flooded to their spill level like any depression, so the lake drains through its
outlet and the cells below a dam keep draining downstream. A lake seeded as a
sink would capture them back over a carved dam. The sink role belongs to the
consumer that walks D: the drainage mover stops at the first lake cell, and the
reach rectification stops at a lake shore.

A constant-head cell has the same two roles. It seeds the flood, so the bowl
around it drains to it as it stands. It keeps its steepest descent as a
receiver, like a rim seed, so the accumulation crosses a river CHD and the
outlet still sums the whole domain. The walks that must end where water leaves
the model (the drainage mover, the reach rectification) read
:attr:`Descent.stopping_receiver`, which is -1 on ``constant_head``.

The basin of D at the outlet of the catchment (:func:`descent_basin`) is the
catchment of a run: the budget zone, the discharge a gauge sees and the
drainage routing all read it. It is computed here and nowhere else.

The arguments of :func:`build_descent` read as follows. ``routable`` names the
cells of the graph, lake cells included: a lake is crossed by the fill, so a
fixed-area lake, inactive in the solver, must be routable here. ``base_level``
adds seeds to the rim of the routable domain, the constant-head cells where water
leaves the model inside it.

``outlet`` replaces the rim by one cell, for a domain that is the catchment
itself: water leaves it at its outlet, not along its whole edge. The connected
parts of the graph that do not hold the outlet keep their rim as seeds, since no
flood from the outlet reaches them. Every seed, rim or constant head, keeps its
steepest descent: the accumulation passes through it, and the walks that stop
there read :attr:`Descent.stopping_receiver`. ``diagonal_neighbors`` asks for the
D8 descent; it holds on a quad mesh and falls back to shared faces elsewhere.

``channel`` flags the cells of the channel tree A and ``pinned_receiver`` gives
each channel cell the next channel cell along A (-1 where free). A pinned cell
drains to its pin, adjacent or not, even where T climbs along A: the flood visits
a pinned cell only from its pin and raises the copy there when needed, so the pin
is always lower. A seed is never pinned.

Off the channel the flood rises by ``2 * epsilon`` per step, on it by ``epsilon``.
A filled flat then climbs faster away from the channel than along it, so its
steepest descent heads INTO the channel instead of running beside it down to the
spill point, which is where the reaches of A would lose their drainage. Without
channel cells every step is ``epsilon`` and D is the plain flood of the stream
criterion.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, replace
from typing import Literal

import numpy as np

from hydromodpy.core.drainage.distance import (
    DownslopeMetric,
    build_downslope_metric,
    resolve_diagonal_neighbors,
    resolve_outlet,
    shared_node_adjacency,
)
from hydromodpy.core.drainage.filling import DEFAULT_EPSILON_M
from hydromodpy.core.drainage.graph import (
    DownhillGraph,
    active_surface_mask,
    cell_adjacency_from_face_connectivity,
    cell_centroids_from_mesh,
    domain_edge_cells,
)
from hydromodpy.core.drainage.pins import cell_mask, resolve_pins, with_pins

__all__ = (
    "BASIN_VERSION",
    "BasinRule",
    "Descent",
    "DescentBasin",
    "build_descent",
    "descent_basin",
    "descent_from_stored_mesh",
    "descent_graph",
)

BasinRule = Literal["near_point", "within_polygon", "largest_basin"]
"""How the outlet of a basin of D was found: the closing point, the polygon, or neither."""

BASIN_VERSION = 1
"""Version of the basin rule, stored with the basin so a reader knows which rule made it."""


@dataclass(frozen=True, slots=True)
class Descent:
    """A filled copy of the model top and the receiver graph it defines.

    ``base_level`` holds the flood seeds: the rim of the routable domain and
    the declared constant-head cells, which ``constant_head`` flags apart.
    Every routable cell outside it has a receiver, and the receiver chains
    never cycle. A seed keeps its steepest descent, -1 only where no neighbor
    is lower, so the accumulation passes through a constant-head cell.

    ``raised`` flags the cells the flood raised on the copy, lakes and pins
    included: where the routing departs from T. ``channel`` flags the cells of the channel tree A, ``pinned`` the channel
    cells whose receiver is their pin rather than their steepest descent.
    The report keeps lake flooding apart from pit filling: ``n_raised`` and
    ``max_raise_m`` count the raised cells outside lakes, ``n_lake_flooded``
    and ``max_lake_flood_m`` the lake cells flooded to their spill level, and
    ``n_pinned_raised``, ``max_pinned_raise_m`` the pinned cells raised so A
    can be followed where T climbs along it.

    ``adjacency`` holds the neighbor sets the flood walked. It is the heavy
    part of D, and :meth:`without_adjacency` drops it once the build is done.
    """

    metric: DownslopeMetric
    surface: np.ndarray
    adjacency: list[set[int]] | None
    base_level: np.ndarray
    constant_head: np.ndarray
    raised: np.ndarray
    lake_of: np.ndarray
    channel: np.ndarray
    pinned: np.ndarray
    n_raised: int
    max_raise_m: float
    n_lake_flooded: int
    max_lake_flood_m: float
    n_pinned_raised: int
    max_pinned_raise_m: float

    @property
    def receiver(self) -> np.ndarray:
        """Receiver of each cell, -1 at an outlet or off the graph."""
        return self.metric.graph.downstream

    @property
    def stopping_receiver(self) -> np.ndarray:
        """Receiver of a walk that ends where water leaves the model.

        Same as :attr:`receiver`, with -1 on the constant-head cells: a reach
        reaching one is the outlet reach, a drain chain reaching one keeps a
        plain drain.
        """
        return np.where(self.constant_head, -1, self.receiver)

    def without_adjacency(self) -> Descent:
        """Return this D without its neighbor sets, for a model to keep.

        The consumers after the build read the receivers, the order, the
        surface, the masks, the edge lengths and the centroids. The adjacency
        sets weigh most of D on a large mesh and nothing reads them anymore.
        """
        return replace(self, adjacency=None)

    @property
    def routable(self) -> np.ndarray:
        """Cells of the descended graph."""
        return self.metric.graph.active

    @property
    def diagonal_neighbors(self) -> bool:
        """Whether the graph pairs cells by shared nodes (D8 on quads)."""
        return self.metric.diagonal_neighbors

    @property
    def n_channel(self) -> int:
        """Number of channel cells on the graph."""
        return int(np.count_nonzero(self.channel))

    @property
    def n_pinned(self) -> int:
        """Number of channel cells whose receiver is their pin."""
        return int(np.count_nonzero(self.pinned))

    def basin(self, outlet: int) -> np.ndarray:
        """Cells whose receiver chain passes through ``outlet``, outlet included."""
        receiver = self.receiver
        inside = np.zeros(receiver.size, dtype=bool)
        if not self.routable[int(outlet)]:
            raise ValueError(f"cell {int(outlet)} is off the descended graph: it closes no basin.")
        inside[int(outlet)] = True
        # Ascending surface: a receiver is strictly lower than its donor, so it
        # is settled before every cell that drains into it.
        for cell in self.metric.graph.order[::-1].tolist():
            target = int(receiver[cell])
            if target >= 0 and inside[target]:
                inside[cell] = True
        return inside


@dataclass(frozen=True, slots=True)
class DescentBasin:
    """The basin of D at the outlet of the catchment: the cells that drain through it.

    ``mask`` holds the outlet. ``rule`` says how the outlet was found: near the
    closing point, inside the watershed polygon, or the largest basin of the
    domain when the run has neither. ``seeded_at_outlet`` says D was flooded
    from this outlet, the domain being the catchment itself.

    ``catchment_fraction`` is the share of each cell's area inside the
    delineated catchment polygon, one value per cell in [0, 1], None when the
    run has no polygon. It weights a catchment total of a spatial quantity
    (recharge, seepage) and never changes ``mask``: what drains to the outlet
    stays whole cells.
    """

    mask: np.ndarray
    outlet: int
    rule: BasinRule
    area_m2: float
    seeded_at_outlet: bool
    catchment_fraction: np.ndarray | None = None

    @property
    def is_catchment(self) -> bool:
        """Whether the basin closes a catchment, not just the largest basin of the domain."""
        return self.rule != "largest_basin"


def descent_basin(
    descent: Descent,
    *,
    cell_area_m2: np.ndarray,
    near: tuple[float, float] | None = None,
    within: np.ndarray | None = None,
    seeded_at_outlet: bool = False,
) -> DescentBasin:
    """Return the basin of D at the outlet of the catchment, the one computation of it.

    The outlet follows the rule of the stream criterion
    (:func:`hydromodpy.core.drainage.distance.resolve_outlet`): the most drained
    cell within two rings of ``near``, else inside ``within``, else the largest
    basin of the domain. The basin follows :attr:`Descent.receiver`, never the
    stopping receiver: it continues through a constant-head cell that has a
    lower neighbor. A constant-head cell with none is a sink, and the cells
    draining into it stay outside.

    Raises
    ------
    ValueError
        When ``cell_area_m2`` does not match the mesh, or ``near`` is given to
        a D whose adjacency was already dropped.
    """
    areas = np.asarray(cell_area_m2, dtype=float).reshape(-1)
    if areas.size != descent.receiver.size:
        raise ValueError(
            f"cell_area_m2 holds {areas.size} cells, the descent {descent.receiver.size}."
        )
    if near is not None and descent.adjacency is None:
        raise ValueError(
            "snapping the outlet near a point needs the adjacency of D: compute the basin "
            "before D drops it."
        )
    rule: BasinRule = (
        "near_point"
        if near is not None
        else "within_polygon"
        if within is not None
        else "largest_basin"
    )
    outlet = resolve_outlet(
        descent.metric,
        near=near,
        within=within,
        adjacency=descent.adjacency,
        cell_area_m2=areas,
    )
    mask = descent.basin(outlet)
    area = float(np.where(np.isfinite(areas), areas, 0.0)[mask].sum())
    return DescentBasin(
        mask=mask,
        outlet=outlet,
        rule=rule,
        area_m2=area,
        seeded_at_outlet=bool(seeded_at_outlet),
    )


def build_descent(
    top: np.ndarray,
    face_node_connectivity: np.ndarray,
    *,
    vertices: np.ndarray,
    centroids: np.ndarray,
    routable: np.ndarray,
    base_level: np.ndarray | None = None,
    lake_of: np.ndarray | None = None,
    pinned_receiver: np.ndarray | None = None,
    channel: np.ndarray | None = None,
    diagonal_neighbors: bool = True,
    epsilon: float = DEFAULT_EPSILON_M,
    outlet: int | None = None,
) -> Descent:
    """Fill a copy of ``top`` on the descended graph and build its receivers.

    The module docstring says what each argument does to the flood.

    Raises
    ------
    ValueError
        When an array does not match the mesh, a lake cell is not routable, a pin is out
        of range, leaves a non-channel cell, lands on a lake, a non-channel or an off-graph
        cell, or closes a cycle, when ``outlet`` is off the graph, or a cell has no way down.
    """
    surface_in = np.asarray(top, dtype=float).reshape(-1)
    n_cells = int(surface_in.size)
    routable_mask = cell_mask(routable, n_cells, "routable")
    on_graph = routable_mask & np.isfinite(surface_in)
    constant_head = np.zeros(n_cells, dtype=bool)
    if base_level is not None:
        constant_head = cell_mask(base_level, n_cells, "base_level") & on_graph
    lakes = _lake_ids(lake_of, n_cells, on_graph)

    use_diagonals = resolve_diagonal_neighbors(
        face_node_connectivity, n_cells=n_cells, requested=bool(diagonal_neighbors)
    )
    adjacency = (
        shared_node_adjacency(face_node_connectivity, n_cells=n_cells)
        if use_diagonals
        else cell_adjacency_from_face_connectivity(face_node_connectivity, n_cells=n_cells)
    )
    seeds = _rim_seeds(outlet, adjacency, face_node_connectivity, on_graph) | constant_head
    if not np.any(seeds):
        raise ValueError("the descent has no seed: no routable cell lies on the domain rim.")
    channel_mask, pin = resolve_pins(
        pinned_receiver, channel, routable_mask, on_graph, lakes, n_cells
    )
    pin[seeds] = -1
    pinned = pin >= 0

    step = np.where(channel_mask | ~np.any(channel_mask), float(epsilon), 2.0 * float(epsilon))
    tolerance = _flood_tolerance(surface_in[on_graph])
    surface, raised = _flood(surface_in, on_graph, adjacency, seeds, pin, step, tolerance=tolerance)

    metric = build_downslope_metric(
        surface,
        face_node_connectivity,
        vertices=vertices,
        centroids=centroids,
        inactive_mask=~on_graph,
        diagonal_neighbors=use_diagonals,
        adjacency=adjacency,
    )
    metric = with_pins(metric, pin)
    _check_every_cell_drains(metric.graph.downstream, surface, on_graph & ~seeds)
    return Descent(
        metric=metric,
        surface=surface,
        adjacency=adjacency,
        base_level=seeds,
        constant_head=constant_head,
        raised=raised,
        lake_of=lakes,
        channel=channel_mask,
        pinned=pinned,
        **_raise_reports(surface - surface_in, raised, lakes >= 0, pinned),
    )


def _lake_ids(lake_of: np.ndarray | None, n_cells: int, on_graph: np.ndarray) -> np.ndarray:
    """Return the lake id of each cell (-1 off the lakes), refusing a lake off the graph."""
    lakes = (
        np.full(n_cells, -1, dtype=int)
        if lake_of is None
        else np.asarray(lake_of, dtype=int).reshape(-1).copy()
    )
    if lakes.size != n_cells:
        raise ValueError(f"lake_of holds {lakes.size} cells, the top {n_cells}.")
    stranded_lake = (lakes >= 0) & ~on_graph
    if np.any(stranded_lake):
        raise ValueError(
            f"{int(stranded_lake.sum())} lake cell(s) are not routable or have no finite "
            "top: a lake is crossed by the descent, so its cells must be on the graph."
        )
    return lakes


def descent_graph(receiver: np.ndarray, surface: np.ndarray) -> DownhillGraph:
    """Rebuild the receiver graph of a stored descent from its two arrays.

    Every link of D strictly descends on D's surface, so ordering the routable
    cells by descending surface gives the donors-before-receivers order the
    accumulation needs. The routable cells are the ones D's surface holds a
    value on. This is what lets a reader route on D without the mesh geometry.
    """
    values = np.asarray(surface, dtype=float).reshape(-1)
    downstream = np.asarray(receiver, dtype=np.int64).reshape(-1)
    if downstream.size != values.size:
        raise ValueError(
            f"the descent holds {downstream.size} receivers and {values.size} surface values."
        )
    active = np.isfinite(values)
    order_all = np.argsort(np.where(active, values, -np.inf), kind="stable")[::-1]
    return DownhillGraph(downstream=downstream, order=order_all[active[order_all]], active=active)


def descent_from_stored_mesh(
    top: np.ndarray, face_node_connectivity: np.ndarray, vertices: np.ndarray
) -> Descent:
    """Rebuild D from a stored mesh, for a run sealed before D was stored.

    The mesh carries neither the channel tree, nor the constant-head cells, nor
    the lakes of the build, so this D has no pin, no constant-head seed and no
    lake: it is the plain flood of the model top, seeded on the domain rim, on
    the D8 neighborhood the mesh allows.
    """
    surface = np.asarray(top, dtype=float).reshape(-1)
    return build_descent(
        surface,
        face_node_connectivity,
        vertices=vertices,
        centroids=cell_centroids_from_mesh(vertices, face_node_connectivity),
        routable=active_surface_mask(surface),
    )


def _rim_seeds(
    outlet: int | None,
    adjacency: list[set[int]],
    face_node_connectivity: np.ndarray,
    on_graph: np.ndarray,
) -> np.ndarray:
    """Return the domain rim, or for a domain that is its catchment the outlet alone.

    The connected part of the graph that holds the outlet is seeded there
    alone. A part detached from it, an island the raster clip of the
    catchment left, keeps its rim, or no flood would ever reach its cells.
    """
    if outlet is None:
        return domain_edge_cells(face_node_connectivity, on_graph)
    outlet = int(outlet)
    if not 0 <= outlet < on_graph.size or not on_graph[outlet]:
        raise ValueError(f"the outlet cell {outlet} is off the descended graph.")
    reached = np.zeros(on_graph.size, dtype=bool)
    reached[outlet] = True
    frontier = [outlet]
    while frontier:
        following: list[int] = []
        for cell in frontier:
            for neighbour in adjacency[cell]:
                if on_graph[neighbour] and not reached[neighbour]:
                    reached[neighbour] = True
                    following.append(neighbour)
        frontier = following
    seeds = domain_edge_cells(face_node_connectivity, on_graph) & ~reached
    seeds[outlet] = True
    return seeds


def _flood(
    top: np.ndarray,
    on_graph: np.ndarray,
    adjacency: list[set[int]],
    seeds: np.ndarray,
    pin: np.ndarray,
    step: np.ndarray,
    *,
    tolerance: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Priority flood from the seeds, pinned cells entered from their pin only.

    The key is (level, cell), the order of the stream criterion's fill, so
    without pins and channel the copy is the criterion's own.
    """
    surface = np.where(on_graph, top, np.nan)
    raised = np.zeros(top.size, dtype=bool)
    visited = ~on_graph
    donors: dict[int, list[int]] = {}
    for cell in np.flatnonzero(pin >= 0).tolist():
        donors.setdefault(int(pin[cell]), []).append(cell)

    frontier: list[tuple[float, int]] = []
    for cell in np.flatnonzero(seeds).tolist():
        visited[cell] = True
        heapq.heappush(frontier, (float(surface[cell]), cell))
    while frontier:
        level, cell = heapq.heappop(frontier)
        candidates = list(adjacency[cell])
        candidates.extend(donors.get(cell, ()))
        for neighbour in candidates:
            if visited[neighbour] or (pin[neighbour] >= 0 and pin[neighbour] != cell):
                continue
            visited[neighbour] = True
            # Within the receiver tolerance a cell would not see this one as
            # lower, so it is raised like a cell below the level.
            if surface[neighbour] <= level + tolerance:
                surface[neighbour] = level + step[neighbour]
                raised[neighbour] = True
            heapq.heappush(frontier, (float(surface[neighbour]), neighbour))

    unreached = np.flatnonzero(~visited)
    if unreached.size:
        raise ValueError(
            f"{unreached.size} cell(s) of the descent are never reached from a seed "
            f"(first: {int(unreached[0])}): the pinned cells around them are entered "
            "only from pins that lie beyond them."
        )
    return surface, raised


def _flood_tolerance(values: np.ndarray) -> float:
    """Return twice the drop below which the receiver graph sees no descent.

    The receiver graph measures its tolerance on the filled range, a little
    wider than the range of the top; doubling it covers that difference.
    """
    span = float(np.ptp(values)) if values.size else 0.0
    return 2.0 * max(1.0e-9, 1.0e-9 * max(abs(span), 1.0))


def _check_every_cell_drains(
    receiver: np.ndarray, surface: np.ndarray, must_drain: np.ndarray
) -> None:
    """Raise unless every non-seed cell has a receiver and every link descends."""
    no_way_down = must_drain & (receiver < 0)
    if np.any(no_way_down):
        raise ValueError(
            f"{int(no_way_down.sum())} cell(s) of the descent have no receiver although "
            f"the flood reached each from a lower cell "
            f"(first: {int(np.flatnonzero(no_way_down)[0])})."
        )
    donors = np.flatnonzero(receiver >= 0)
    climbing = donors[~(surface[receiver[donors]] < surface[donors])]
    if climbing.size:
        raise ValueError(
            f"{climbing.size} receiver link(s) of the descent do not descend "
            f"(first from cell {int(climbing[0])}): the receiver chains could cycle."
        )


def _raise_reports(
    rise: np.ndarray, raised: np.ndarray, lake: np.ndarray, pinned: np.ndarray
) -> dict[str, int | float]:
    """Count the raised cells and their largest rise: off the lakes, on them, on the pins."""
    reports: dict[str, int | float] = {}
    for count, largest, selected in (
        ("n_raised", "max_raise_m", raised & ~lake),
        ("n_lake_flooded", "max_lake_flood_m", raised & lake),
        ("n_pinned_raised", "max_pinned_raise_m", raised & pinned),
    ):
        reports[count] = int(np.count_nonzero(selected))
        reports[largest] = float(np.max(rise[selected])) if reports[count] else 0.0
    return reports
