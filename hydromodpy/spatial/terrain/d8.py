"""Where each cell of a D8 pointer raster drains, read from the code table of the port."""

from __future__ import annotations

from typing import Literal

import numpy as np

from hydromodpy.spatial.terrain.port import D8_WBT_OFFSETS


def d8_receivers(pointer: np.ndarray, *, pit: Literal["none", "self"]) -> np.ndarray:
    """Return the flat index of the cell each cell of *pointer* drains to.

    *pointer* holds the ``d8_wbt`` codes of :data:`D8_WBT_OFFSETS`. A cell has
    no receiver at a pit, at a nodata or unknown code, or when its step leaves
    the grid. Its receiver is then ``-1`` when *pit* is ``"none"``, and its own
    index when *pit* is ``"self"``. The result is flat, row after row.
    """
    codes = np.asarray(pointer)
    n_rows, n_cols = codes.shape
    if pit == "self":
        receivers = np.arange(codes.size, dtype=np.int64)
    else:
        receivers = np.full(codes.size, -1, dtype=np.int64)
    flat_codes = codes.reshape(-1)
    for code, (d_row, d_col) in D8_WBT_OFFSETS.items():
        source = np.flatnonzero(flat_codes == code)
        if source.size == 0:
            continue
        rows, cols = np.divmod(source, n_cols)
        to_row = rows + d_row
        to_col = cols + d_col
        inside = (to_row >= 0) & (to_row < n_rows) & (to_col >= 0) & (to_col < n_cols)
        receivers[source[inside]] = to_row[inside] * n_cols + to_col[inside]
    return receivers


__all__ = ["d8_receivers"]
