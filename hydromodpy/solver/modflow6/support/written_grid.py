"""What flopy keeps of a mesh when it writes it into a MODFLOW 6 file.

A mesh is stored in float64 and in the ring order the cell mesh gives. The
solver reads it back from text, rounded, and DISV wants clockwise rings. These
two helpers say how far the written grid may differ from the stored one.
"""

from __future__ import annotations

import numpy as np


def written_step(values: np.ndarray) -> np.ndarray:
    """Return the rounding step flopy applies to each value it writes to a MODFLOW 6 file.

    Flopy 3.10 keeps eight decimals, and nine significant digits above 1e5 or
    below 1e-3 in magnitude. Two coordinates closer than half a step are the
    same coordinate to the solver.
    """
    magnitude = np.abs(np.asarray(values, dtype=np.float64))
    scaled = (magnitude > 1e5) | ((magnitude > 0.0) & (magnitude < 1e-3))
    exponent = np.floor(np.log10(np.where(scaled, magnitude, 1.0)))
    return np.where(scaled, 10.0 ** (exponent - 8.0), 1e-8)


def reoriented_rows(rows: np.ndarray) -> np.ndarray:
    """Return padded cell rows with each ring walked the other way, first node kept.

    ``[n0, n1, ..., n_k-1]`` becomes ``[n0, n_k-1, ..., n1]``; the ``-1`` padding stays.
    """
    size = (rows >= 0).sum(axis=1)[:, None]
    columns = np.arange(rows.shape[1])[None, :]
    order = np.where(columns == 0, 0, np.where(columns < size, size - columns, columns))
    return np.take_along_axis(rows, order, axis=1)
