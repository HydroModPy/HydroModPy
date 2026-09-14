"""WhiteboxTools D8 flow-pointer encoding (shared).

WBT with ``esri_pntr=False`` stores, per cell, the power-of-two code pointing at
its single downslope neighbour, laid out clockwise from the north-east::

     64  128    1
     32    X    2
     16    8    4

This maps each code to a ``(drow, dcol)`` offset, with ``drow`` counted downward
because a raster's first row is its northernmost. A pit, nodata, or any other
code has no downstream cell.

This is NOT the ESRI encoding, which starts at the east and which every code
here would shift by one octant. The two are one 45 degree rotation apart, so a
mix-up does not fail: every descent simply walks beside the talweg instead of
down it, and the flow paths look plausible while being wrong. The convention is
verified against the solver by
``tests/unit/geographic/test_d8_pointer_convention.py``, which tilts a plane in
each cardinal direction and reads back the code Whitebox writes.
"""

from __future__ import annotations

# code -> (drow, dcol)
WBT_D8_OFFSETS: dict[int, tuple[int, int]] = {
    1: (-1, 1),  # NE
    2: (0, 1),  # E
    4: (1, 1),  # SE
    8: (1, 0),  # S
    16: (1, -1),  # SW
    32: (0, -1),  # W
    64: (-1, -1),  # NW
    128: (-1, 0),  # N
}
