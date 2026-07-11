"""WhiteboxTools D8 flow-pointer encoding (shared).

WBT with ``esri_pntr=False`` stores, per cell, the power-of-two code pointing at
its single downslope neighbour. This maps each code to a ``(drow, dcol)`` offset.
A pit / nodata / any other code has no downstream cell.
"""

from __future__ import annotations

# code -> (drow, dcol)
WBT_D8_OFFSETS: dict[int, tuple[int, int]] = {
    1: (0, 1),  # E
    2: (1, 1),  # SE
    4: (1, 0),  # S
    8: (1, -1),  # SW
    16: (0, -1),  # W
    32: (-1, -1),  # NW
    64: (-1, 0),  # N
    128: (-1, 1),  # NE
}
