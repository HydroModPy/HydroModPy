"""The vertical column of a layered model, read from its ``idomain``.

A model is a stack of layers over planar cells. ``idomain`` says, per layer and
cell, whether the cell is active (1), inactive (0) or a vertical pass-through
(-1, MODFLOW 6). A cell is active when its ``idomain`` is above 0. Every layer
that asks for "the top of the aquifer" reads the top active cell of the column
through this module, so a stack whose top layer is partly inactive needs no
change in its consumers.
"""

from __future__ import annotations

import numpy as np

IDOMAIN_VALUES = (-1, 0, 1)
"""Values an ``idomain`` may hold: pass-through, inactive, active."""

VERTICAL_LAYOUT_COLUMN_FRACTIONS = "column_fractions"
"""``vertical_layout`` of a stack whose layers are shares of the column between
the top and the base of the aquifer. A run stores it on its ``mesh/`` group."""

VERTICAL_LAYOUT_SURFACES = "surfaces"
"""``vertical_layout`` of a stack whose layers each end on a base surface of their own."""


def top_active_layer(idomain: np.ndarray) -> np.ndarray:
    """Return, per column, the index of the top active layer, -1 for a column with none.

    ``idomain`` has shape ``(n_layers, n_cells)``; a 1-D array is one layer.
    """
    active = np.atleast_2d(np.asarray(idomain)) > 0
    layer = np.argmax(active, axis=0).astype(np.int64)
    layer[~active.any(axis=0)] = -1
    return layer


def values_at_layer(values: np.ndarray, layer: np.ndarray) -> np.ndarray:
    """Return ``values[layer[c], c]`` per column ``c``, NaN where ``layer`` is -1.

    ``values`` has shape ``(n_layers, n_cells)`` or ``(n_steps, n_layers, n_cells)``.
    """
    data = np.asarray(values, dtype="float64")
    index = np.asarray(layer, dtype=np.int64).reshape(-1)
    cells = np.arange(index.size)
    safe = np.where(index < 0, 0, index)
    picked = data[..., safe, cells]
    return np.where(index < 0, np.nan, picked)


def layer_interfaces(top: np.ndarray, botm: np.ndarray) -> np.ndarray:
    """Return the ``(n_layers + 1, n_cells)`` interfaces: the top, then each layer bottom."""
    top_row = np.asarray(top, dtype="float64").reshape(1, -1)
    return np.vstack([top_row, np.atleast_2d(np.asarray(botm, dtype="float64"))])


def check_layer_interfaces(top: np.ndarray, botm: np.ndarray, idomain: np.ndarray) -> None:
    """Refuse interfaces an active or pass-through cell cannot hold.

    An active cell has a positive thickness; a pass-through cell (-1) may be
    flat but never upside down. An inactive cell (0) is not read. The check
    names the first offending cell with its layer counted from 0.

    Raises
    ------
    ValueError
        When an interface rises below a cell that is read.
    """
    domain = np.atleast_2d(np.asarray(idomain))
    interfaces = layer_interfaces(top, botm)
    thickness = interfaces[:-1] - interfaces[1:]
    with np.errstate(invalid="ignore"):
        bad = ((domain > 0) & ~(thickness > 0.0)) | ((domain < 0) & ~(thickness >= 0.0))
    if not bad.any():
        return
    layer, cell = (int(v) for v in np.argwhere(bad)[0])
    raise ValueError(
        f"{int(bad.sum())} cell(s) of the layer stack have a top below their bottom, "
        f"first layer {layer} cell {cell} (top {interfaces[layer, cell]:.3f} m, "
        f"bottom {interfaces[layer + 1, cell]:.3f} m, idomain {int(domain[layer, cell])}). "
        "An active cell needs a positive thickness."
    )


__all__ = [
    "IDOMAIN_VALUES",
    "VERTICAL_LAYOUT_COLUMN_FRACTIONS",
    "VERTICAL_LAYOUT_SURFACES",
    "check_layer_interfaces",
    "layer_interfaces",
    "top_active_layer",
    "values_at_layer",
]
