"""The descent D: where water goes on the model top, as a computation only.

Routing needs a surface on which every cell drains. The model top T is not one:
projected onto a mesh it holds pits the routing DEM never had, and raising T
until it drains would change the ground the solver sees. D resolves this on a
COPY of T (principle P2 of the network architecture): the copy is filled so each
cell holds a descending path to a base level, and it never returns to the solver.
The channel bed, the drain elevations and the reach tops keep reading T.

The fill runs on the very graph that is descended. A flood only guarantees a
strictly lower neighbour among the cells it walked, so a fill on one
neighbourhood and a descent on another leave filled cells spilling over a link
the descent cannot take (see the comment in
:func:`hydromodpy.core.stream_geometry.build_network_geometry`). D floods like
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
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, replace

import numpy as np

from hydromodpy.core.depression_filling import DEFAULT_EPSILON_M
from hydromodpy.core.field_routing import (
    DownhillGraph,
    active_surface_mask,
    cell_adjacency_from_face_connectivity,
    cell_centroids_from_mesh,
    domain_edge_cells,
)
from hydromodpy.core.topographic_distance import (
    DownslopeMetric,
    build_downslope_metric,
    resolve_diagonal_neighbors,
    shared_node_adjacency,
)

__all__ = ("Descent", "build_descent", "descent_from_stored_mesh", "descent_graph")


@dataclass(frozen=True, slots=True)
class Descent:
    """A filled copy of the model top and the receiver graph it defines.

    ``base_level`` holds the flood seeds: the rim of the routable domain and
    the declared constant-head cells, which ``constant_head`` flags apart.
    Every routable cell outside it has a receiver, and the receiver chains
    never cycle. A seed keeps its steepest descent, -1 only where no neighbour
    is lower, so the accumulation passes through a constant-head cell.

    ``raised`` flags the cells the flood raised on the copy, lakes and pins
    included: where the routing departs from T. ``channel`` flags the cells of the channel tree A, ``pinned`` the channel
    cells whose receiver is their pin rather than their steepest descent.
    The report keeps lake flooding apart from pit filling: ``n_raised`` and
    ``max_raise_m`` count the raised cells outside lakes, ``n_lake_flooded``
    and ``max_lake_flood_m`` the lake cells flooded to their spill level, and
    ``n_pinned_raised``, ``max_pinned_raise_m`` the pinned cells raised so A
    can be followed where T climbs along it.

    ``adjacency`` holds the neighbour sets the flood walked. It is the heavy
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
        """Return this D without its neighbour sets, for a model to keep.

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

    def lake_spill_cell(self, lake: int) -> int:
        """First cell outside ``lake`` on its descent, -1 if it drains off the domain.

        The fill leaves the lowest lake cell next to the spill point, so its
        receiver is the cell the lake overflows into.
        """
        cells = np.flatnonzero(self.lake_of == int(lake))
        if cells.size == 0:
            raise ValueError(f"lake {int(lake)} holds no cell of the descent.")
        lowest = int(cells[np.argmin(self.surface[cells])])
        return int(self.receiver[lowest])


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
) -> Descent:
    """Fill a copy of ``top`` on the descended graph and build its receivers.

    ``routable`` names the cells of the graph, lake cells included: a lake is
    crossed by the fill, so a fixed-area lake, inactive in the solver, must be
    routable here. ``base_level`` adds seeds to the rim of the routable domain,
    the constant-head cells where water leaves the model inside it. Every seed,
    rim or constant head, keeps its steepest descent: the accumulation passes
    through it, and the walks that stop there read
    :attr:`Descent.stopping_receiver`. ``diagonal_neighbors`` asks
    for the D8 descent; it holds on a quad mesh and falls back to shared faces
    elsewhere.

    ``channel`` flags the cells of the channel tree A and ``pinned_receiver``
    gives each channel cell the next channel cell along A (-1 where free). A
    pinned cell drains to its pin, adjacent or not, even where T climbs along
    A: the flood visits a pinned cell only from its pin and raises the copy
    there when needed, so the pin is always lower. A seed is never pinned.

    Off the channel the flood rises by ``2 * epsilon`` per step, on it by
    ``epsilon``. A filled flat then climbs faster away from the channel than
    along it, so its steepest descent heads INTO the channel instead of
    running beside it down to the spill point, which is where the reaches of
    A would lose their drainage. Without channel cells every step is
    ``epsilon`` and D is the plain flood of the stream criterion.

    Raises
    ------
    ValueError
        When an array does not match the mesh, a lake cell is not routable, a
        pin is out of range, leaves a non-channel cell, lands on a lake, a
        non-channel or an off-graph cell, or closes a cycle, or when a cell is
        left with no way down.
    """
    surface_in = np.asarray(top, dtype=float).reshape(-1)
    n_cells = int(surface_in.size)
    routable_mask = _cell_mask(routable, n_cells, "routable")
    on_graph = routable_mask & np.isfinite(surface_in)
    extra_seeds = (
        np.zeros(n_cells, dtype=bool)
        if base_level is None
        else _cell_mask(base_level, n_cells, "base_level")
    )
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

    use_diagonals = resolve_diagonal_neighbors(
        face_node_connectivity, n_cells=n_cells, requested=bool(diagonal_neighbors)
    )
    adjacency = (
        shared_node_adjacency(face_node_connectivity, n_cells=n_cells)
        if use_diagonals
        else cell_adjacency_from_face_connectivity(face_node_connectivity, n_cells=n_cells)
    )
    constant_head = extra_seeds & on_graph
    seeds = domain_edge_cells(face_node_connectivity, on_graph) | constant_head
    if not np.any(seeds):
        raise ValueError("the descent has no seed: no routable cell lies on the domain rim.")
    channel_mask, pin = _resolve_pins(
        pinned_receiver, channel, routable_mask, on_graph, lakes, n_cells
    )
    pin[seeds] = -1
    pinned = pin >= 0

    step = np.full(n_cells, float(epsilon))
    if np.any(channel_mask):
        step[~channel_mask] = 2.0 * float(epsilon)
    surface, raised = _flood(
        surface_in,
        on_graph,
        adjacency,
        seeds,
        pin,
        step,
        tolerance=_flood_tolerance(surface_in[on_graph]),
    )

    metric = build_downslope_metric(
        surface,
        face_node_connectivity,
        vertices=vertices,
        centroids=centroids,
        inactive_mask=~on_graph,
        diagonal_neighbors=use_diagonals,
        adjacency=adjacency,
    )
    metric = _with_pins(metric, pin)
    _check_every_cell_drains(metric.graph.downstream, surface, on_graph & ~seeds)

    lake = lakes >= 0
    rise = np.where(raised, surface - surface_in, 0.0)
    n_raised, max_raise = _raise_report(rise, raised & ~lake)
    n_flooded, max_flood = _raise_report(rise, raised & lake)
    n_pinned_raised, max_pinned_raise = _raise_report(rise, raised & pinned)
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
        n_raised=n_raised,
        max_raise_m=max_raise,
        n_lake_flooded=n_flooded,
        max_lake_flood_m=max_flood,
        n_pinned_raised=n_pinned_raised,
        max_pinned_raise_m=max_pinned_raise,
    )


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
    the D8 neighbourhood the mesh allows.
    """
    surface = np.asarray(top, dtype=float).reshape(-1)
    return build_descent(
        surface,
        face_node_connectivity,
        vertices=vertices,
        centroids=cell_centroids_from_mesh(vertices, face_node_connectivity),
        routable=active_surface_mask(surface),
    )


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


def _resolve_pins(
    pinned_receiver: np.ndarray | None,
    channel: np.ndarray | None,
    routable: np.ndarray,
    on_graph: np.ndarray,
    lakes: np.ndarray,
    n_cells: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Validate the channel and its pins, and return them on the graph."""
    pin = np.full(n_cells, -1, dtype=int)
    if pinned_receiver is not None:
        values = np.asarray(pinned_receiver).reshape(-1)
        if values.size != n_cells:
            raise ValueError(f"pinned_receiver holds {values.size} cells, the top {n_cells}.")
        if values.size and not np.issubdtype(values.dtype, np.integer):
            raise ValueError("pinned_receiver must hold integer cell ids, -1 where free.")
        out_of_range = np.flatnonzero((values < -1) | (values >= n_cells))
        if out_of_range.size:
            cell = int(out_of_range[0])
            raise ValueError(
                f"cell {cell} is pinned to {int(values[cell])}, outside [-1, {n_cells})."
            )
        pin = values.astype(int, copy=True)

    if channel is None:
        if np.any(pin >= 0):
            raise ValueError("pinned_receiver needs channel: a pin runs between channel cells.")
        return np.zeros(n_cells, dtype=bool), pin
    channel_mask = _cell_mask(channel, n_cells, "channel")
    _refuse_first(channel_mask & ~routable, "cell {} is a channel cell off the routable graph.")
    _refuse_first(channel_mask & (lakes >= 0), "cell {} is a channel cell inside a lake.")

    donors = np.flatnonzero(pin >= 0)
    targets = pin[donors]
    checks = (
        (~channel_mask[donors], "cell {} is pinned but is not a channel cell."),
        (~on_graph[donors], "cell {} is pinned but has no finite top on the graph."),
        (lakes[targets] >= 0, "cell {} is pinned onto a lake cell."),
        (~channel_mask[targets], "cell {} is pinned onto a cell outside the channel."),
        (~on_graph[targets], "cell {} is pinned onto a cell off the graph."),
    )
    for failed, message in checks:
        if np.any(failed):
            raise ValueError(message.format(int(donors[np.argmax(failed)])))
    _refuse_pin_cycle(pin)
    return channel_mask & on_graph, pin


def _refuse_pin_cycle(pin: np.ndarray) -> None:
    """Raise when following the pins comes back to a cell already on the path."""
    state = np.zeros(pin.size, dtype=np.int8)  # 0 new, 1 on the current path, 2 done
    for start in np.flatnonzero(pin >= 0).tolist():
        path: list[int] = []
        cell = start
        while cell >= 0 and state[cell] == 0:
            state[cell] = 1
            path.append(cell)
            cell = int(pin[cell])
        if cell >= 0 and state[cell] == 1:
            raise ValueError(f"the pins hold a cycle through cell {cell}.")
        state[path] = 2


def _refuse_first(failed: np.ndarray, message: str) -> None:
    if np.any(failed):
        raise ValueError(message.format(int(np.argmax(failed))))


def _with_pins(metric: DownslopeMetric, pin: np.ndarray) -> DownslopeMetric:
    """Return ``metric`` with pinned cells sent to their pin."""
    downstream = metric.graph.downstream.copy()
    pinned = pin >= 0
    downstream[pinned] = pin[pinned]
    edge_length = metric.edge_length.copy()
    if np.any(pinned):
        delta = metric.centroids[pinned] - metric.centroids[pin[pinned]]
        edge_length[pinned] = np.hypot(delta[:, 0], delta[:, 1])
    # A pin is strictly lower than its donor, so the descending order still holds.
    graph = DownhillGraph(
        downstream=downstream, order=metric.graph.order, active=metric.graph.active
    )
    return DownslopeMetric(
        graph=graph,
        edge_length=edge_length,
        centroids=metric.centroids,
        diagonal_neighbors=metric.diagonal_neighbors,
    )


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


def _raise_report(rise: np.ndarray, selected: np.ndarray) -> tuple[int, float]:
    count = int(np.count_nonzero(selected))
    return count, float(np.max(rise[selected])) if count else 0.0


def _cell_mask(values: np.ndarray, n_cells: int, name: str) -> np.ndarray:
    mask = np.asarray(values, dtype=bool).reshape(-1)
    if mask.size != n_cells:
        raise ValueError(f"{name} holds {mask.size} cells, the top {n_cells}.")
    return mask
