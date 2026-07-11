"""Reconcile a regridded lake bed to the abacus by area-weighted quantile mapping.

The abacus stage-area curve ``sarea(stage)`` is the wetted lake area at each
stage, i.e. the (unnormalized) cumulative plan-area of bed below that elevation.
A coarse mesh sampled from bathymetry rarely reproduces that hypsometry exactly.
This module keeps the SPATIAL PATTERN of the regridded bed (which cell is deep,
which is shallow) but re-assigns the elevations so the cell area-below-elevation
distribution matches the abacus. It is an exact, one-pass monotone remap (quantile
mapping), not an iterative DEM optimizer: many beds share one hypsometric curve,
so the curve only constrains the distribution of depths, never their location.

The mesh footprint area and the abacus full-pool area can differ; the remap
scales the abacus area axis onto the footprint so the hypsometric SHAPE is
preserved and the simulated volume matches up to that footprint-area ratio.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping, Sequence

import numpy as np

# Warn when the mesh footprint area diverges from the abacus full-pool area by more
# than this fraction: the remap stretches storage onto the footprint, so a large gap
# means a bad lake polygon or a coarse boundary is shifting every reconciled bed.
_AREA_SCALE_WARN_TOL = 0.05

__all__ = ["reconcile_bed_to_abacus"]


def reconcile_bed_to_abacus(
    *,
    bed_by_cell: Mapping[int, float],
    area_by_cell: Mapping[int, float],
    abacus_stage: Sequence[float],
    abacus_sarea: Sequence[float],
) -> tuple[dict[int, float], dict[str, float]]:
    """Return ``({cell_id: carved_bed}, diagnostics)``.

    Parameters
    ----------
    bed_by_cell : regridded bed elevation per lake cell (may contain NaN).
    area_by_cell : plan area per lake cell (same keys).
    abacus_stage, abacus_sarea : the abacus stage and wetted-surface-area columns,
        sorted by increasing stage, ``sarea`` non-decreasing.

    The deepest cells (lowest regridded bed) are assigned the lowest abacus
    stages; ties break by cell id for determinism. Cells with a NaN regridded bed
    are placed at the median depth so they still receive a valid elevation.
    """
    cells = sorted(int(c) for c in bed_by_cell)
    if not cells:
        raise ValueError("reconcile_bed_to_abacus: no lake cells")

    stage = np.asarray(abacus_stage, dtype=float)
    sarea = np.asarray(abacus_sarea, dtype=float)
    if stage.size < 2 or stage.size != sarea.size:
        raise ValueError("reconcile_bed_to_abacus: abacus needs >= 2 aligned stage/sarea rows")
    if np.any(np.diff(stage) <= 0.0):
        raise ValueError("reconcile_bed_to_abacus: abacus stage must be strictly increasing")
    if np.any(np.diff(sarea) < -1e-9):
        raise ValueError("reconcile_bed_to_abacus: abacus sarea must be non-decreasing")

    beds = np.array([bed_by_cell[c] for c in cells], dtype=float)
    areas = np.array([float(area_by_cell[c]) for c in cells], dtype=float)
    if np.any(areas <= 0.0):
        raise ValueError("reconcile_bed_to_abacus: cell areas must be positive")

    finite = np.isfinite(beds)
    if not np.any(finite):
        raise ValueError("reconcile_bed_to_abacus: no finite regridded bed to rank")
    if not np.all(finite):
        beds = beds.copy()
        beds[~finite] = float(np.median(beds[finite]))

    footprint_area = float(np.sum(areas))
    abacus_area_max = float(sarea[-1])
    if abacus_area_max <= 0.0:
        raise ValueError("reconcile_bed_to_abacus: abacus top sarea must be positive")
    scale = footprint_area / abacus_area_max
    if abs(scale - 1.0) > _AREA_SCALE_WARN_TOL:
        warnings.warn(
            f"lake bed reconcile: mesh footprint area ({footprint_area:.0f} m2) departs from "
            f"the abacus full-pool area ({abacus_area_max:.0f} m2) by "
            f"{abs(scale - 1.0) * 100:.1f}% (area_scale={scale:.3f}); simulated storage is "
            f"stretched onto the footprint, so a bad lake polygon or a coarse mesh boundary "
            f"shifts every reconciled bed elevation.",
            RuntimeWarning,
            stacklevel=2,
        )

    # Rank cells deepest-first; ties by cell id (cells already id-sorted).
    order = np.argsort(beds, kind="stable")
    areas_sorted = areas[order]
    cum = np.cumsum(areas_sorted)
    cum_mid = cum - 0.5 * areas_sorted  # plan area at the middle of each ranked cell

    carved_sorted = np.array(
        [_sarea_inverse(stage, sarea, a_mid / scale) for a_mid in cum_mid],
        dtype=float,
    )

    carved = np.empty_like(carved_sorted)
    carved[order] = carved_sorted
    bed_out = {cells[i]: float(carved[i]) for i in range(len(cells))}

    diagnostics = {
        "footprint_area": footprint_area,
        "abacus_area_max": abacus_area_max,
        "area_scale": scale,
        "n_cells": float(len(cells)),
        "n_bed_filled": float(int(np.count_nonzero(~finite))),
        "carved_bed_min": float(np.min(carved)),
        "carved_bed_max": float(np.max(carved)),
    }
    return bed_out, diagnostics


def _sarea_inverse(stage: np.ndarray, sarea: np.ndarray, target_area: float) -> float:
    """Smallest stage whose wetted area reaches ``target_area`` (lower edge on a plateau)."""
    if target_area <= sarea[0]:
        return float(stage[0])
    if target_area >= sarea[-1]:
        return float(stage[-1])
    for i in range(sarea.size - 1):
        s0 = sarea[i]
        s1 = sarea[i + 1]
        if s1 <= target_area:
            continue
        if s0 >= target_area:
            return float(stage[i])
        frac = (target_area - s0) / (s1 - s0)
        return float(stage[i] + frac * (stage[i + 1] - stage[i]))
    return float(stage[-1])
