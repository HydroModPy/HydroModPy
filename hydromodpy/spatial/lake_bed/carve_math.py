"""Re-grade one mesh column around a carved lake-bed elevation.

Carving the bed must keep the column a valid prism: strictly decreasing layer
bottoms, every layer thinner-bounded by ``min_thickness``, and the aquifer base
fixed. The bottom of the deepest OCCUPIED (inactive) layer is set to the bed, so
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
) -> np.ndarray:
    """Return new layer bottoms for one column with the bed at ``botm[occupied_layers-1]``.

    ``top`` is left unchanged (the lake-cell top stays the impounded surface). The
    aquifer base ``botm_col[-1]`` is kept fixed. The bed is clamped into
    ``[base + min_thickness, top - min_thickness]`` so the column stays valid.
    """
    botm_col = np.asarray(botm_col, dtype=float)
    nlay = botm_col.size
    occ = int(occupied_layers)
    if occ < 1 or occ >= nlay:
        raise ValueError(
            f"regrade_column_to_bed: occupied_layers={occ} must satisfy 1 <= occ < nlay={nlay}"
        )

    base = float(botm_col[-1])
    bed_hi = float(top) - float(min_thickness)
    bed_lo = base + float(min_thickness)
    if bed_lo > bed_hi:
        raise ValueError(
            f"regrade_column_to_bed: column too thin (top={top}, base={base}) for "
            f"min_thickness={min_thickness}"
        )
    bed_clamped = float(np.clip(bed, bed_lo, bed_hi))

    new_botm = botm_col.copy()
    new_botm[:occ] = _regrade_segment(
        orig_top=float(top),
        orig_bottoms=botm_col[:occ],
        top_edge=float(top),
        bot_edge=bed_clamped,
    )
    new_botm[occ:] = _regrade_segment(
        orig_top=float(botm_col[occ - 1]),
        orig_bottoms=botm_col[occ:],
        top_edge=bed_clamped,
        bot_edge=base,
    )
    return new_botm


def regrade_column_active_top(
    *,
    orig_top: float,
    botm_col: np.ndarray,
    bed: float,
    min_thickness: float,
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
    bed_hi = float(orig_top) - float(min_thickness)
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
    )
    return bed_clamped, new_botm


def _regrade_segment(
    *,
    orig_top: float,
    orig_bottoms: np.ndarray,
    top_edge: float,
    bot_edge: float,
) -> np.ndarray:
    """Re-proportion a run of layer bottoms into ``[bot_edge, top_edge]``."""
    orig_bottoms = np.asarray(orig_bottoms, dtype=float)
    tops = np.concatenate(([orig_top], orig_bottoms[:-1]))
    thick = tops - orig_bottoms
    total = float(np.sum(thick))
    if total <= 0.0:
        frac = np.full(orig_bottoms.size, 1.0 / orig_bottoms.size)
    else:
        frac = thick / total
    new_total = top_edge - bot_edge
    new_bottoms = top_edge - np.cumsum(frac) * new_total
    new_bottoms[-1] = bot_edge
    return new_bottoms
