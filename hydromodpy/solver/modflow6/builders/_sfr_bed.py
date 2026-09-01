"""Streambed elevation profile for one SFR network.

The SFR path already verifies that water ROUTES correctly: no cycle, a
downstream-increasing numbering, a signed connectivity. Nothing verified that a
reach bed sits where the terrain is. A bed can land tens of metres under the
land surface, or perched above it, and every topological check still passes.

That gap has a measured cost. MODFLOW 6 switches a reach between connected and
disconnected at ``rtp - rbth`` (``gwf-sfr.f90:3973-3985``: ``bt = strtop -
bthick`` then ``h_temp = max(hgwf, bt)``), so a bed placed away from the water
table toggles at every outer iteration. On the Nancon at 25 m one reach sat
0.59 m ABOVE the land surface and the daily transient stalled on a 0.3 mm
two-state cycle.

One-sided sweeps cannot fix it, and the repository held one of each pointing in
opposite directions: ``_sfr_network.py`` only lowered the downstream reach, the
builder only lifted the upstream one. Lowering incises (measured -29.80 m),
lifting perches (measured +27.08 m on 2355 of 3041 reaches). This module makes the
CELL the hard constraint and the downhill order the soft one, in a single
downstream pass, and reports every reach where the two disagree.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

# A bed sitting exactly on the cell bottom leaves no saturated thickness for the
# exchange; MODFLOW 6 refuses `bt <= botm` outright (gwf-sfr.f90:4337-4348).
RTP_ABOVE_BOTTOM_M = 0.1


def _cell_top(top: np.ndarray, botm: np.ndarray, layer: int, cell: int) -> float:
    """Top of the reach's OWN cell, which is the layer top, not the model top.

    ``SolverMesh.top`` is ``(n_cells,)``: the top of layer 0 only. A reach whose
    first active layer is deeper (``_first_active_layer`` scans down from 0)
    has its top at the bottom of the layer above.
    """
    return float(top[cell]) if layer <= 0 else float(botm[layer - 1, cell])


def solve_reach_bed_profile(
    reaches: Sequence[Any],
    *,
    top: np.ndarray | None,
    botm: np.ndarray | None,
    rbth: float,
    min_slope: float,
    bed_incision: float | None,
    max_bed_sag: float,
    location: str,
) -> dict[int, float]:
    """Return one streambed top per ``ifno``, inside its cell and downhill where it can be.

    Every bed lands inside the box its own cell allows; that box is a hard
    constraint and an empty one is refused by name. The monotone-downhill order
    is then held wherever the boxes allow it, and relaxed with a warning where a
    climbing traced channel makes it impossible. ``bed_incision = None`` keeps
    the historical behaviour: a floor on the cell bottom and no ceiling.
    """
    by_ifno: Mapping[int, Any] = {record.ifno: record for record in reaches}
    order = [record.ifno for record in reaches]
    target = {record.ifno: float(record.rtp) for record in reaches}

    def drop(up: int, down: int) -> float:
        return min_slope * 0.5 * (float(by_ifno[up].rlen) + float(by_ifno[down].rlen))

    # Each reach's own box, from ITS cell. An empty box here is a real
    # impossibility: the aquifer cannot hold the declared bed, and no ordering
    # choice can rescue it, so it is refused by name.
    lo: dict[int, float] = {}
    hi: dict[int, float] = {}
    for record in reaches:
        low, high = -np.inf, np.inf
        if record.cellid is not None and botm is not None:
            layer, cell = int(record.cellid[0]), int(record.cellid[1])
            low = float(botm[layer, cell]) + float(rbth) + RTP_ABOVE_BOTTOM_M
            if bed_incision is not None and top is not None:
                high = _cell_top(top, botm, layer, cell) - float(bed_incision)
                low = max(low, high - float(max_bed_sag))
        if low > high:
            cell_txt = "no cell" if record.cellid is None else f"cell {tuple(record.cellid)}"
            raise ValueError(
                f"{location} reach {record.ifno} ({cell_txt}) cannot hold a streambed: its "
                f"own cell leaves the band [{low:.3f}, {high:.3f}] m empty. The aquifer is "
                f"too thin there for bed_incision plus streambed_thickness; lower "
                f"bed_incision, thin streambed_thickness, or deepen the layer."
            )
        lo[record.ifno], hi[record.ifno] = low, high

    # Pass 1, upstream. A floored downstream reach raises the floor of everything
    # above it, and only a pass in this direction can see that: a downstream pass
    # has already fixed the upstream value by the time the floor fires. Capped by
    # the cell ceiling, because the cell is the hard constraint.
    relaxed: list[tuple[int, float]] = []
    for ifno in reversed(order):
        for down in by_ifno[ifno].downstream:
            required = lo[down] + drop(ifno, down)
            if required > hi[ifno]:
                relaxed.append((ifno, required - hi[ifno]))
                required = hi[ifno]
            lo[ifno] = max(lo[ifno], required)

    # Pass 2, downstream. The numbering is topological (asserted upstream of
    # here), so every upstream neighbour is already final and the monotone
    # constraint reads straight off it.
    #
    # Where the cell box and the downhill order disagree, the BOX WINS. A bed
    # belongs where the terrain is: MODFLOW 6 only requires rtp - rbth to stay
    # above the cell bottom, and it routes on the declared connectivity, not on
    # elevations. Forcing the order instead is what incised beds 29.80 m under
    # the surface, and forcing it the other way perched 2355 of 3041 reaches.
    # A traced channel that climbs is a defect of the trace, and it is reported
    # as such rather than absorbed into a wrong geometry.
    solved: dict[int, float] = {}
    for ifno in order:
        upper = hi[ifno]
        for up in by_ifno[ifno].upstream:
            upper = min(upper, solved[up] - drop(up, ifno))
        if upper < lo[ifno]:
            relaxed.append((ifno, lo[ifno] - upper))
            solved[ifno] = lo[ifno]
        else:
            solved[ifno] = min(max(target[ifno], lo[ifno]), upper)

    if relaxed:
        worst_ifno, worst_step = max(relaxed, key=lambda item: item[1])
        logger.warning(
            "%s streambed profile: %d/%d reach(es) could not hold the downhill order "
            "inside their own cell and kept the cell instead; worst step up %.2f m at "
            "reach %d. The traced channel climbs there, which is a defect of the trace.",
            location,
            len(relaxed),
            len(order),
            worst_step,
            worst_ifno,
        )

    if bed_incision is not None and top is not None and botm is not None:
        moved = [
            abs(solved[record.ifno] - target[record.ifno])
            for record in reaches
            if record.cellid is not None
        ]
        if moved and max(moved) > 1e-6:
            logger.info(
                "%s streambed profile: %d/%d reach(es) moved to hold the band "
                "[cell top - %.2f m - %.2f m, cell top - %.2f m] and the downstream order "
                "(max move %.2f m).",
                location,
                sum(1 for value in moved if value > 1e-6),
                len(moved),
                float(bed_incision),
                float(max_bed_sag),
                float(bed_incision),
                max(moved),
            )
    return solved
