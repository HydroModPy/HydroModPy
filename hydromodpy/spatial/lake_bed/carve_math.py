"""Re-grade one mesh column around a carved lake-bed elevation.

Carving the bed must keep the column a valid prism: strictly decreasing layer
bottoms and the aquifer base fixed. The bed is clamped so each segment has room
for its layers at ``min_thickness``, and the re-grade then holds that floor on
EVERY layer: each one is given ``min_thickness`` first and only the surplus is
shared out in proportion to the original thicknesses. The bottom of the deepest
OCCUPIED (inactive) layer is set to the bed, so
the first ACTIVE cell below has its top at the real bed and the LAK vertical
connection exchanges there. The inactive cap ``[bed, top]`` and the active aquifer
``[base, bed]`` are each re-proportioned from the original layer thicknesses, so
the vertical discretization style is preserved on both sides of the bed.
"""

from __future__ import annotations

import numpy as np

__all__ = ["regrade_column_active_top", "regrade_column_to_bed"]


def regrade_column_to_bed(
    *,
    top: float,
    botm_col: np.ndarray,
    bed: float,
    occupied_layers: int,
    min_thickness: float,
    stage_max: float | None = None,
) -> np.ndarray:
    """Return new layer bottoms for one column with the bed at ``botm[occupied_layers-1]``.

    ``top`` is left unchanged (the lake-cell top stays the impounded surface). The
    aquifer base ``botm_col[-1]`` is kept fixed. The bed is clamped so each segment
    can hold its layers at ``>= min_thickness``: the occupied cap ``[bed, top]`` has
    ``occ`` layers and the active segment ``[base, bed]`` has ``nlay - occ``. Each
    segment then re-proportions the original thicknesses ON TOP of a
    ``min_thickness`` floor given to every layer, so no layer of a valid column
    ends up thinner than the floor. A column too thin to hold both segments at the
    floor raises instead.
    """
    botm_col = np.asarray(botm_col, dtype=float)
    nlay = botm_col.size
    occ = int(occupied_layers)
    if occ < 1 or occ >= nlay:
        raise ValueError(
            f"regrade_column_to_bed: occupied_layers={occ} must satisfy 1 <= occ < nlay={nlay}"
        )

    base = float(botm_col[-1])
    bed_hi = _bed_ceiling(float(top) - occ * float(min_thickness), stage_max)
    bed_lo = base + (nlay - occ) * float(min_thickness)
    if bed_lo > bed_hi:
        raise ValueError(
            f"regrade_column_to_bed: column too thin (top={top}, base={base}) to hold "
            f"{occ} cap and {nlay - occ} active layers at min_thickness={min_thickness}"
        )
    bed_clamped = float(np.clip(bed, bed_lo, bed_hi))

    new_botm = botm_col.copy()
    new_botm[:occ] = _regrade_segment(
        orig_top=float(top),
        orig_bottoms=botm_col[:occ],
        top_edge=float(top),
        bot_edge=bed_clamped,
        min_thickness=float(min_thickness),
    )
    new_botm[occ:] = _regrade_segment(
        orig_top=float(botm_col[occ - 1]),
        orig_bottoms=botm_col[occ:],
        top_edge=bed_clamped,
        bot_edge=base,
        min_thickness=float(min_thickness),
    )
    return new_botm


def regrade_column_active_top(
    *,
    orig_top: float,
    botm_col: np.ndarray,
    bed: float,
    min_thickness: float,
    stage_max: float | None = None,
) -> tuple[float, np.ndarray]:
    """Re-grade one column for the active-littoral (marnage) representation.

    The cell stays active and its TOP becomes the bathymetric ``bed`` (so a
    VERTICAL LAK connection gates wetting on the real bed). All ``nlay`` layers
    are re-proportioned into ``[base, bed]`` with the aquifer base fixed; nothing
    is deactivated. Returns ``(new_top, new_botm)``. ``bed`` is clamped into
    ``[base + nlay*min_thickness, orig_top - min_thickness]``.
    """
    botm_col = np.asarray(botm_col, dtype=float)
    nlay = botm_col.size
    base = float(botm_col[-1])
    bed_hi = _bed_ceiling(float(orig_top) - float(min_thickness), stage_max)
    bed_lo = base + nlay * float(min_thickness)
    if bed_lo > bed_hi:
        raise ValueError(
            f"regrade_column_active_top: column too thin (top={orig_top}, base={base}) for "
            f"{nlay} layers at min_thickness={min_thickness}"
        )
    bed_clamped = float(np.clip(bed, bed_lo, bed_hi))
    new_botm = _regrade_segment(
        orig_top=float(orig_top),
        orig_bottoms=botm_col,
        top_edge=bed_clamped,
        bot_edge=base,
        min_thickness=float(min_thickness),
    )
    return bed_clamped, new_botm



def _bed_ceiling(terrain_ceiling: float, stage_max: float | None) -> float:
    """Highest bed a column may carry, given the terrain and the lake full pool.

    The terrain ceiling alone is the wrong reference for a bed that came out of
    ``reconcile_bed_to_abacus``. That bed is an absolute elevation read off the
    abacus stage axis, whose top is the full-pool level; the model top is the DEM,
    which over an impounded valley sits BELOW full pool on most of the footprint.
    Clamping to the DEM therefore undoes the reconciliation it was just asked for,
    and it can only push the bed DOWN, so it deepens the cuvette and inflates the
    storage. The reconciled bed reproduces the reference abacus to round-off; the
    clamp then pins every cell whose terrain sits below its assigned stage to
    ``top - min_thickness`` and deepens the cuvette by the mean of those shifts.
    Lowering ``min_thickness`` barely helps, which is the tell: the floor is not the
    problem, the reference the ceiling is measured from is.

    Raising the ceiling to the full-pool stage makes the upper clamp inert for a
    reconciled bed (which never exceeds that stage by construction) while leaving
    it in place for a raw regridded bed, which is unbounded. ``bed_lo`` is
    untouched: it is the real geometric constraint, and it never binds here.
    """
    if stage_max is None:
        return terrain_ceiling
    return max(terrain_ceiling, float(stage_max))

def _regrade_segment(
    *,
    orig_top: float,
    orig_bottoms: np.ndarray,
    top_edge: float,
    bot_edge: float,
    min_thickness: float,
) -> np.ndarray:
    """Re-proportion a run of layer bottoms into ``[bot_edge, top_edge]``.

    Every layer keeps at least ``min_thickness``: the floor is allocated first and
    only the surplus is shared out in proportion to the original thicknesses. A
    purely proportional split would starve a thin layer of a very uneven column
    (bottoms ``[90, 80, 50]`` re-graded into a 2 m segment give 0.5 m and 1.5 m),
    which is exactly the degenerate cell the floor exists to prevent. Callers
    clamp the segment edges so the room is always there.
    """
    orig_bottoms = np.asarray(orig_bottoms, dtype=float)
    count = orig_bottoms.size
    tops = np.concatenate(([orig_top], orig_bottoms[:-1]))
    thick = tops - orig_bottoms
    total = float(np.sum(thick))
    if total <= 0.0:
        frac = np.full(count, 1.0 / count)
    else:
        frac = thick / total
    new_total = float(top_edge) - float(bot_edge)
    floor = max(float(min_thickness), 0.0)
    surplus = new_total - count * floor
    if surplus > 0.0:
        new_thick = floor + frac * surplus
    else:
        # No room for the floor (the caller's clamp guarantees this cannot happen
        # for a valid column): fall back to an even split, still monotonic.
        new_thick = np.full(count, new_total / count)
    new_bottoms = top_edge - np.cumsum(new_thick)
    new_bottoms[-1] = bot_edge
    return new_bottoms
