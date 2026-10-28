"""Compute the simulated abacus by flooding a per-cell lake bed.

Given the carved (or raw) bed elevation and plan area of each lake cell, the
stage-volume-area relation the model actually represents is, at stage ``z``:

* wetted area  ``A(z) = sum(area_c for bed_c < z)``
* storage      ``V(z) = sum(area_c * max(0, z - bed_c))``

Comparing this simulated abacus to the user abacus is the diagnostic that tells
whether the carved bed reproduces the real filling.

Reconcile a regridded lake bed to the abacus by area-weighted quantile mapping.

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

from hydromodpy.core.logging import get_logger

__all__ = [
    "simulate_abacus",
    "reconcile_bed_to_abacus",
]


def simulate_abacus(
    *,
    bed_by_cell: Mapping[int, float],
    area_by_cell: Mapping[int, float],
    stages: Sequence[float],
) -> dict[str, np.ndarray]:
    """Return ``{'stage', 'volume', 'sarea'}`` arrays from a per-cell bed.

    ``stages`` are the elevations at which to evaluate the flooded volume and
    wetted area (typically the abacus stage column, so the curves are directly
    comparable).
    """
    cells = sorted(int(c) for c in bed_by_cell)
    if not cells:
        raise ValueError("simulate_abacus: no lake cells")
    bed = np.array([float(bed_by_cell[c]) for c in cells], dtype=float)
    area = np.array([float(area_by_cell[c]) for c in cells], dtype=float)
    stage = np.asarray(stages, dtype=float)

    depth = stage[:, None] - bed[None, :]  # (n_stages, n_cells)
    wet = depth > 0.0
    volume = np.sum(np.where(wet, depth, 0.0) * area[None, :], axis=1)
    sarea = np.sum(np.where(wet, area[None, :], 0.0), axis=1)
    return {"stage": stage, "volume": volume, "sarea": sarea}


logger = get_logger(__name__)

# Warn when the mesh footprint area diverges from the abacus full-pool area by more
# than this fraction: the remap stretches storage onto the footprint, so a large gap
# means a bad lake polygon or a coarse boundary is shifting every reconciled bed.
_AREA_SCALE_WARN_TOL = 0.05


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
    stage, sarea = _checked_abacus(abacus_stage, abacus_sarea)

    beds = np.array([bed_by_cell[c] for c in cells], dtype=float)
    areas = np.array([float(area_by_cell[c]) for c in cells], dtype=float)
    if np.any(areas <= 0.0):
        raise ValueError("reconcile_bed_to_abacus: cell areas must be positive")
    beds, n_filled = _beds_with_gaps_at_the_median(beds)

    footprint_area = float(np.sum(areas))
    abacus_area_max = float(sarea[-1])
    scale = footprint_area / abacus_area_max
    if abs(scale - 1.0) > _AREA_SCALE_WARN_TOL:
        message = (
            f"lake bed reconcile: mesh footprint area ({footprint_area:.0f} m2) departs from "
            f"the abacus full-pool area ({abacus_area_max:.0f} m2) by "
            f"{abs(scale - 1.0) * 100:.1f}% (area_scale={scale:.3f}); simulated storage is "
            f"stretched onto the footprint, so a bad lake polygon or a coarse mesh boundary "
            f"shifts every reconciled bed elevation."
        )
        logger.warning(message)
        warnings.warn(message, RuntimeWarning, stacklevel=2)

    carved = _quantile_mapped(beds, areas, stage, sarea, scale)
    bed_out = {cells[i]: float(carved[i]) for i in range(len(cells))}
    diagnostics = {
        "footprint_area": footprint_area,
        "abacus_area_max": abacus_area_max,
        "area_scale": scale,
        "n_cells": float(len(cells)),
        "n_bed_filled": float(n_filled),
        "carved_bed_min": float(np.min(carved)),
        "carved_bed_max": float(np.max(carved)),
    }
    return bed_out, diagnostics


def _checked_abacus(
    abacus_stage: Sequence[float], abacus_sarea: Sequence[float]
) -> tuple[np.ndarray, np.ndarray]:
    """Return the abacus columns as arrays, or refuse an abacus the remap cannot invert."""
    stage = np.asarray(abacus_stage, dtype=float)
    sarea = np.asarray(abacus_sarea, dtype=float)
    if stage.size < 2 or stage.size != sarea.size:
        raise ValueError("reconcile_bed_to_abacus: abacus needs >= 2 aligned stage/sarea rows")
    if np.any(np.diff(stage) <= 0.0):
        raise ValueError("reconcile_bed_to_abacus: abacus stage must be strictly increasing")
    if np.any(np.diff(sarea) < -1e-9):
        raise ValueError("reconcile_bed_to_abacus: abacus sarea must be non-decreasing")
    if sarea[-1] <= 0.0:
        raise ValueError("reconcile_bed_to_abacus: abacus top sarea must be positive")
    return stage, sarea


def _beds_with_gaps_at_the_median(beds: np.ndarray) -> tuple[np.ndarray, int]:
    """Place a cell with a NaN bed at the median bed; return the beds and the count filled."""
    finite = np.isfinite(beds)
    if not np.any(finite):
        raise ValueError("reconcile_bed_to_abacus: no finite regridded bed to rank")
    if not np.all(finite):
        beds = beds.copy()
        beds[~finite] = float(np.median(beds[finite]))
    return beds, int(np.count_nonzero(~finite))


def _quantile_mapped(
    beds: np.ndarray, areas: np.ndarray, stage: np.ndarray, sarea: np.ndarray, scale: float
) -> np.ndarray:
    """Give each cell the abacus stage whose scaled wetted area reaches its ranked mid area."""
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
    return carved


def _sarea_inverse(stage: np.ndarray, sarea: np.ndarray, target_area: float) -> float:
    """Smallest stage whose wetted area reaches ``target_area`` (lower edge on a plateau)."""
    if target_area <= sarea[0]:
        return float(stage[0])
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
