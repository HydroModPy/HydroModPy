"""Monotone channel breach (network safety net) on a mesh face graph.

The priority-flood fill drains hillslopes but is blunt on channels: it can only
RAISE cells, so where a channel cell sits below its downstream neighbour the fill
lifts it, burying the thalweg (measured at 5 m: the zonal channel-min lowers
channel cells, then the fill re-raises ~3 % of them and creates a handful of
inversions). This carves the channel DOWN instead, so the thalweg descends
monotonically to a lake/boundary outlet and the fill never has to touch it.

Flow direction comes from the network topology, not elevation: a BFS from the
outlet channel cells over the channel subgraph gives each cell its downstream
parent (the neighbour nearer the outlet). Cells are then swept leaves-first, each
pushing its downstream parent below it by ``epsilon`` (at a confluence the parent
takes the lowest of its children, a min). Lower-only and capped: a cell is never
raised, never carved below ``floor`` (botm0 + min_thickness) nor more than
``max_lowering_m``; outlet cells anchor at their own top. Pure graph + arrays.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

import numpy as np

_TOL_M = 1e-6


def _downstream_parents(
    channel: np.ndarray,
    adjacency: list[set[int]],
    outlets: set[int],
) -> tuple[dict[int, int], list[int]]:
    """BFS the channel subgraph from the outlets; return parent map + visit order."""
    parent: dict[int, int] = {}
    order: list[int] = []
    seen = set(outlets)
    queue: deque[int] = deque(outlets)
    for o in outlets:
        order.append(o)
    while queue:
        u = queue.popleft()
        for v in adjacency[u]:
            if channel[v] and v not in seen:
                seen.add(v)
                parent[v] = u  # u is nearer the outlet -> u is v's downstream
                order.append(v)
                queue.append(v)
    return parent, order


def breach_channel_corridor(
    top: np.ndarray,
    *,
    adjacency: list[set[int]],
    channel_cells: Iterable[int],
    outlet_cells: Iterable[int] | None = None,
    floor: np.ndarray | None = None,
    epsilon: float = 1e-3,
    max_lowering_m: float = 5.0,
) -> tuple[np.ndarray, dict[str, float]]:
    """Return a top whose channel cells descend monotonically toward their outlet.

    Parameters
    ----------
    top :
        (n_cells,) current per-cell top.
    adjacency :
        cell -> face-adjacent neighbour set.
    channel_cells :
        The channel cell ids (thalweg corridor) to breach.
    outlet_cells :
        Channel cells that are drainage exits (adjacent to a lake or the domain
        boundary); they anchor at their top. When ``None`` or empty the lowest
        channel cell is used as the single outlet.
    floor :
        (n_cells,) hard lower bound; a cell is never carved below it.
    epsilon :
        Minimal drop enforced between a channel cell and its downstream neighbour.
    max_lowering_m :
        Cap on how far a single channel cell may be carved below its input top.
    """
    orig = np.asarray(top, dtype=float).reshape(-1)
    carved = orig.copy()
    n_cells = int(carved.shape[0])
    channel = np.zeros(n_cells, dtype=bool)
    ch_idx = np.fromiter((int(c) for c in channel_cells), dtype=int)
    if ch_idx.size:
        channel[ch_idx] = True
    floor_arr = None if floor is None else np.asarray(floor, dtype=float).reshape(-1)

    outlets = {int(c) for c in (outlet_cells or ()) if channel[int(c)]}
    if not outlets and channel.any():
        outlets = {int(np.flatnonzero(channel)[np.argmin(carved[channel])])}

    parent, order = _downstream_parents(channel, adjacency, outlets)

    # Leaves first (reverse BFS order): each cell pushes its downstream parent
    # below it. Outlets anchor (never lowered). A parent fed by several children
    # takes the lowest requirement.
    for cell in reversed(order):
        p = parent.get(cell)
        if p is None or p in outlets:
            continue
        need = carved[cell] - epsilon
        if carved[p] <= need:
            continue  # already strictly below its upstream child
        lowered_to = need
        if floor_arr is not None and np.isfinite(floor_arr[p]):
            lowered_to = max(lowered_to, float(floor_arr[p]))
        lowered_to = max(lowered_to, float(orig[p]) - float(max_lowering_m))
        if lowered_to < carved[p]:
            carved[p] = lowered_to

    delta = orig - carved
    lowered_mask = delta > _TOL_M
    info = {
        "channel_cells": float(int(channel.sum())),
        "channel_outlets": float(len(outlets)),
        "channel_unreached": float(int(channel.sum()) - len(order)),
        "cells_lowered": int(lowered_mask.sum()),
        "max_lowering_m": float(delta.max(initial=0.0)),
        "mean_lowering_m": float(delta[lowered_mask].mean()) if lowered_mask.any() else 0.0,
    }
    return carved, info
