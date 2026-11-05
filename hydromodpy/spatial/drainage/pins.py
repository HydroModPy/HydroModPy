"""The channel pins of the descent D: validate them and apply them to the receiver graph.

A pin sends a channel cell to the next channel cell along the channel tree A,
adjacent or not, even where the model top climbs along A. The flood of
:func:`hydromodpy.spatial.drainage.descent.build_descent` raises its copy so the pin
is always lower; this module checks the pins before the flood and rewrites the
receivers after it.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.spatial.drainage.distance import DownslopeMetric
from hydromodpy.spatial.drainage.graph import DownhillGraph


def resolve_pins(
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
    channel_mask = cell_mask(channel, n_cells, "channel")
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


def with_pins(metric: DownslopeMetric, pin: np.ndarray) -> DownslopeMetric:
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


def cell_mask(values: np.ndarray, n_cells: int, name: str) -> np.ndarray:
    mask = np.asarray(values, dtype=bool).reshape(-1)
    if mask.size != n_cells:
        raise ValueError(f"{name} holds {mask.size} cells, the top {n_cells}.")
    return mask
