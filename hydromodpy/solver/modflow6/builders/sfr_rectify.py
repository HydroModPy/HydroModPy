"""Rebuild the SFR reach cells as a clean single-flow-direction channel on the mesh.

The raster-delineated stream, intersected with an irregular Voronoi mesh, is both
BRAIDED (clumps of adjacent cells) and GAPPED (the reach connectivity links cells
that do not share a face) and can dead-end mid-catchment (its flow then leaves the
model). Post-hoc adding/removing cells cannot cleanly fix that. Instead the channel is
RE-DERIVED as a single-flow-direction (SFD) path network on the mesh, seeded by the
delineated stream cells: from every seed cell the SFD (steepest descent on the
CONDITIONED mesh top) is traced one face-neighbour at a time until it reaches a lake,
the domain edge, or an already-traced channel cell.

The union of those paths is the channel. By construction it is one cell wide (each
cell has a single downstream), face-continuous (every step crosses a shared face, so
no geometric gap), follows the true thalweg (so the surface flow follows the reach, not
a side spill), and connects to a real sink (no inland dead-end). Each cell keeps the
stream attributes (width, Strahler, streambed properties) of the seed whose trace
reached it; the streambed top is the mesh top, monotone-clamped by ``_number_and_freeze``.
Requires ``[modflow6.sgrid] condition_top = true`` so every cell has a descending path.

``rectify_reach_graph`` returns a ``(nodes, edges)`` graph for ``_number_and_freeze`` to
re-number, so this module never re-implements the Kahn sort / rtp clamp.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh.ops.mesh_flow import (
    lowest_unvisited_neighbour,
    steepest_descent_receiver,
)

logger = get_logger(__name__)


def _upstream_counts(downstream_of: Mapping[int, int | None]) -> dict[int, int]:
    """Transitive number of reach cells upstream of each cell on the channel DAG."""
    cells = list(downstream_of)
    upstream_of: dict[int, list[int]] = {c: [] for c in cells}
    for c, d in downstream_of.items():
        if d is not None and d in upstream_of:
            upstream_of[d].append(c)
    indeg = {c: len(upstream_of[c]) for c in cells}
    queue = deque(c for c in cells if indeg[c] == 0)
    order: list[int] = []
    while queue:  # topological order (upstream cells before their downstream)
        c = queue.popleft()
        order.append(c)
        d = downstream_of.get(c)
        if d is not None and d in indeg:
            indeg[d] -= 1
            if indeg[d] == 0:
                queue.append(d)
    up_count = {c: 0 for c in cells}
    for c in order:
        up_count[c] = sum(1 + up_count[u] for u in upstream_of[c])
    return up_count


def _prune_parallel_stub_cells(
    downstream_of: Mapping[int, int | None],
    cell_adjacency: Sequence[set[int]],
    *,
    max_stub_upstream: int,
) -> set[int]:
    """Cells to KEEP after demoting low-order parallel stubs to hillslope drainage.

    A reach cell whose upstream reach count is at most ``max_stub_upstream`` and that
    shares a face with a reach carrying strictly more upstream cells (the real channel it
    runs beside), other than its own downstream, is a redundant thread of a braided band.
    Such cells are peeled leaf-first, so removing one never orphans a kept upstream, and
    the demoted cells still reach the network as routed DRN. ``up_count`` is the original
    (pre-prune) count, so only genuinely low-order cells are ever demoted.
    """
    up_count = _upstream_counts(downstream_of)
    reach_cells = set(downstream_of)
    upstream_of: dict[int, list[int]] = {c: [] for c in reach_cells}
    for c, d in downstream_of.items():
        if d is not None and d in upstream_of:
            upstream_of[d].append(c)

    kept = set(reach_cells)
    changed = True
    while changed:
        changed = False
        for c in sorted(kept, key=lambda x: up_count[x]):
            if c not in kept or up_count[c] > max_stub_upstream:
                continue
            if any(u in kept for u in upstream_of[c]):
                continue  # not a current leaf: it heads a kept channel, keep it
            down = downstream_of.get(c)
            if any(
                nb != down and nb in kept and nb in reach_cells and up_count[nb] > up_count[c]
                for nb in cell_adjacency[c]
            ):
                kept.discard(c)
                changed = True
    return kept


def _reach_components(downstream_of: Mapping[int, int | None]) -> list[list[int]]:
    """Connected components of the reach graph (undirected up/downstream links)."""
    adjacency: dict[int, set[int]] = {c: set() for c in downstream_of}
    for c, d in downstream_of.items():
        if d is not None and d in adjacency:
            adjacency[c].add(d)
            adjacency[d].add(c)
    seen: set[int] = set()
    comps: list[list[int]] = []
    for start in downstream_of:
        if start in seen:
            continue
        stack, comp = [start], []
        seen.add(start)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adjacency[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        comps.append(comp)
    return comps


def _adjacent_lake(
    cell: int,
    cell_adjacency: Sequence[set[int]],
    lake_cell_to_number: Mapping[int, int],
    top: np.ndarray,
) -> int | None:
    """The lowest lake cell that shares a face with ``cell``, else ``None``.

    A reach cell on the shoreline touches the lake through a shared face and discharges
    into it. Picking the lowest-top neighbour makes the choice deterministic when the
    cell abuts two lakes (the sill between the reservoir and the forebay).
    """
    best, best_top = None, None
    for nb in cell_adjacency[cell]:
        if nb not in lake_cell_to_number:
            continue
        tnb = float(top[nb])
        if best_top is None or tnb < best_top:
            best, best_top = int(nb), tnb
    return best


def _first_active_layer(idomain: np.ndarray, cell2d: int, nlay: int) -> int | None:
    for lay in range(nlay):
        if int(idomain[lay, cell2d]) == 1:
            return lay
    return None


def rectify_reach_graph(
    records: Sequence[Any],
    *,
    mesh_top: np.ndarray,
    cell_adjacency: Sequence[set[int]],
    cell_centroids: np.ndarray,
    lake_cell_to_number: Mapping[int, int],
    boundary_cells: set[int],
    idomain: np.ndarray,
    nlay: int,
    location: str,
    max_stub_upstream: int = 2,
    min_component_cells: int = 2,
    spillway_seeds: set[int] = frozenset(),
) -> tuple[list[dict[str, Any]], list[tuple[int, int]]]:
    """Re-derive one reach network as an SFD channel; return ``(nodes, edges)``.

    ``lake_cell_to_number`` maps a lake cell2d to its 1-based ``terminal_lake`` label.
    ``boundary_cells`` are cells where a reach may leave the model. ``max_stub_upstream``
    demotes low-order parallel stubs to DRN (see ``_prune_parallel_stub_cells``); a
    negative value keeps every traced cell. ``min_component_cells`` drops whole reach
    components smaller than it (a lone one-cell "stream" is hillslope drainage, not a
    channel); a value of 1 keeps every component. ``spillway_seeds`` are extra channel
    heads (a dam toe below a lake outlet) traced down - ignoring lake adjacency, since the
    dam is a wall - until they merge into the channel, so an SFR reach reaches the dam foot.
    """
    top = np.asarray(mesh_top, dtype=float).reshape(-1)
    active = np.asarray(idomain[0] > 0)

    # Seed cells = the delineated stream cells, keyed by cell2d with their attributes.
    seeds: dict[int, Any] = {}
    for rec in records:
        if rec.cellid is not None:
            seeds.setdefault(int(rec.cellid[1]), rec)
    if not seeds:
        return [_node_from_record(r) for r in records], []

    # Trace on the CONDITIONED mesh top so every seed has a strictly descending path to
    # a sink (condition_top removes the projection pits). The channel is then the natural
    # single-flow-direction thalweg through the delineated seeds - which is exactly where
    # the surface water goes, so the flow follows the reach by construction.
    receiver = steepest_descent_receiver(top, cell_adjacency, cell_centroids, active=active)

    # Trace the SFD from every seed to a sink; the union is a clean one-cell channel.
    downstream_of: dict[int, int | None] = {}
    terminal_lake: dict[int, int] = {}
    attr_of: dict[int, Any] = {}
    for seed in seeds:
        cur = seed
        walk_seen: set[int] = set()
        guard = 0
        while cur not in downstream_of and guard <= len(active):
            guard += 1
            walk_seen.add(cur)
            attr_of.setdefault(cur, seeds.get(cur))
            # A cell sharing a face with a lake discharges into it. Lake cells are
            # inactive in the aquifer, so the steepest-descent receiver never steps into
            # them; this recovers the lake terminal by adjacency instead.
            lake_nb = _adjacent_lake(cur, cell_adjacency, lake_cell_to_number, top)
            if lake_nb is not None:
                downstream_of[cur] = None
                terminal_lake[cur] = int(lake_cell_to_number[lake_nb])
                break
            nxt = int(receiver[cur])
            if nxt < 0 or not active[nxt] or nxt in walk_seen:
                # No strict-downhill step (a residual pit, a flat spill created by the
                # priority-flood conditioning, or a loop). A boundary cell leaves the
                # model here; otherwise spill over the lowest unvisited rim and keep
                # descending so the reach still reaches a sink (Rule 1: no inland
                # dead-end whose water leaves the model mid-catchment).
                if cur in boundary_cells:
                    downstream_of[cur] = None
                    break
                spill = lowest_unvisited_neighbour(cur, cell_adjacency, top, active, walk_seen)
                if spill is None:
                    downstream_of[cur] = None  # fully enclosed by visited/inactive cells
                    break
                nxt = spill
            downstream_of[cur] = nxt
            attr_of.setdefault(nxt, attr_of.get(cur))
            if nxt in boundary_cells:
                downstream_of[nxt] = None  # the outlet reach: leaves the model (EXT-OUTFLOW)
                break
            cur = nxt

    # Thin braided bands: demote low-order threads that run beside the true channel to
    # hillslope drainage. A kept cell's downstream is never a demoted leaf, so the edges
    # stay consistent and every kept cell keeps its full path to a sink.
    n_traced = len(downstream_of)
    if max_stub_upstream >= 0:
        kept = _prune_parallel_stub_cells(
            downstream_of, cell_adjacency, max_stub_upstream=max_stub_upstream
        )
        if len(kept) < len(downstream_of):
            downstream_of = {c: d for c, d in downstream_of.items() if c in kept}
            terminal_lake = {c: v for c, v in terminal_lake.items() if c in kept}

    # Drop tiny isolated components: a lone one-cell "stream" that just touches a lake or
    # the outlet is hillslope drainage, not a channel, and reads as a spurious SFR -> lake
    # star. A component is dropped whole (no cross-component edge), so the graph stays
    # consistent; the dropped cells still reach the network as routed DRN.
    if min_component_cells > 1:
        drop = {
            c
            for comp in _reach_components(downstream_of)
            if len(comp) < min_component_cells
            for c in comp
        }
        if drop:
            downstream_of = {c: d for c, d in downstream_of.items() if c not in drop}
            terminal_lake = {c: v for c, v in terminal_lake.items() if c not in drop}

    # Extend the channel up to each spillway discharge cell (the dam toe): trace the SFD
    # DOWN from the seed - ignoring lake adjacency, since the dam is a wall and the toe
    # drains AWAY from the reservoir - until it merges into the (pruned) channel or leaves
    # at the boundary. This puts an SFR reach at the foot of the dam so the overflow feeds
    # the river directly instead of a gap of hillslope DRN cells. Runs after pruning, so
    # these cells are never demoted.
    for seed in spillway_seeds:
        cur = int(seed)
        walk_seen: set[int] = set()
        guard = 0
        while cur not in downstream_of and active[cur] and guard <= len(active):
            guard += 1
            walk_seen.add(cur)
            nxt = int(receiver[cur])
            if nxt < 0 or not active[nxt] or nxt in walk_seen:
                if cur in boundary_cells:
                    downstream_of[cur] = None
                    break
                spill = lowest_unvisited_neighbour(cur, cell_adjacency, top, active, walk_seen)
                if spill is None:
                    downstream_of[cur] = None
                    break
                nxt = spill
            merged = nxt in downstream_of
            downstream_of[cur] = nxt
            if merged:
                break  # cur now flows into the existing channel
            if nxt in boundary_cells:
                downstream_of[nxt] = None
                break
            cur = nxt

    # An intermediate cell with no attributes yet inherits the nearest seed's channel
    # properties (walk down to the first cell that has them).
    for cell in downstream_of:
        if attr_of.get(cell) is None:
            walk, seen = cell, set()
            while (
                attr_of.get(walk) is None
                and downstream_of.get(walk) is not None
                and walk not in seen
            ):
                seen.add(walk)
                walk = downstream_of[walk]
            attr_of[cell] = attr_of.get(walk) or next(iter(seeds.values()))

    has_upstream = {int(d) for d in downstream_of.values() if d is not None}
    index_of = {cell: i for i, cell in enumerate(downstream_of)}
    nodes: list[dict[str, Any]] = []
    for cell in downstream_of:
        layer = _first_active_layer(idomain, cell, nlay)
        nodes.append(
            _channel_node(
                attr_of[cell],
                cell=cell,
                layer=layer,
                top=float(top[cell]),
                is_headwater=cell not in has_upstream,
                terminal_lake=terminal_lake.get(cell),
            )
        )
    edges = [
        (index_of[cell], index_of[down]) for cell, down in downstream_of.items() if down is not None
    ]

    logger.info(
        "%s reach rectification: %d delineated cells -> %d SFD channel cells "
        "(1-cell-wide, face-continuous; %d stub / tiny-component cell(s) demoted to DRN), "
        "%d lake terminal(s).",
        location,
        len(seeds),
        len(nodes),
        n_traced - len(nodes),
        len(terminal_lake),
    )
    return nodes, edges


def _node_from_record(rec: Any) -> dict[str, Any]:
    return {
        "cellid": rec.cellid,
        "rlen": float(rec.rlen),
        "rtp": float(rec.rtp),
        "rgrd": float(rec.rgrd),
        "rwid": float(rec.rwid),
        "strahler": int(rec.strahler),
        "area_km2": float(rec.area_km2),
        "ustrf": float(rec.ustrf),
        "is_headwater": bool(rec.is_headwater),
        "is_terminal_to_lake": bool(rec.is_terminal_to_lake),
        "terminal_lake": rec.terminal_lake,
    }


def _channel_node(
    attr: Any,
    *,
    cell: int,
    layer: int | None,
    top: float,
    is_headwater: bool,
    terminal_lake: int | None,
) -> dict[str, Any]:
    """One channel cell, inheriting stream properties from its seed reach ``attr``."""
    return {
        "cellid": (int(layer), int(cell)) if layer is not None else None,
        "rlen": float(attr.rlen),
        "rtp": top,
        "rgrd": float(attr.rgrd),
        "rwid": float(attr.rwid),
        "strahler": int(attr.strahler),
        "area_km2": float(attr.area_km2),
        "ustrf": 1.0,
        "is_headwater": bool(is_headwater),
        "is_terminal_to_lake": terminal_lake is not None,
        "terminal_lake": terminal_lake,
    }


__all__ = ["rectify_reach_graph"]
