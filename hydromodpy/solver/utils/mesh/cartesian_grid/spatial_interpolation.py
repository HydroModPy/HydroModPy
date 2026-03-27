"""Shared spatial interpolation utilities for structured grids.

Provides nearest-neighbor, linear, and inverse-distance-weighting (IDW)
interpolation from scattered or gridded source data onto 2-D target
cell-center arrays.
"""

from __future__ import annotations

import logging
from typing import Literal

import numpy as np

logger = logging.getLogger(__name__)

InterpolationMethod = Literal["nearest", "linear", "idw"]


def interpolate_to_grid(
    source_values: np.ndarray,
    source_x: np.ndarray,
    source_y: np.ndarray,
    target_x: np.ndarray,
    target_y: np.ndarray,
    nrow: int,
    ncol: int,
    method: InterpolationMethod = "nearest",
    *,
    idw_power: float = 2.0,
) -> np.ndarray:
    """Interpolate source data onto a (nrow, ncol) target grid.

    Parameters
    ----------
    source_values : 2-D or 1-D array of source values.
    source_x, source_y : Source point coordinates.
        1-D arrays for axis coordinates or 2-D meshgrids.
    target_x, target_y : Target cell-center coordinates, shape ``(nrow, ncol)``.
    nrow, ncol : Target grid dimensions.
    method : Interpolation method.
    idw_power : Exponent for IDW weighting (only used when method="idw").

    Returns
    -------
    np.ndarray
        Interpolated values, shape ``(nrow, ncol)``.
    """
    source_values = np.asarray(source_values, dtype=float)

    # Fast path: grids are identical.
    if _grids_are_aligned(source_values, source_x, source_y, target_x, target_y, nrow, ncol):
        return source_values.copy()

    # Build flat source coordinate arrays.
    src_x_flat, src_y_flat, src_v_flat = _flatten_source(
        source_values, source_x, source_y,
    )
    if src_v_flat is None:
        return np.full((nrow, ncol), float(np.nanmean(source_values)), dtype=float)

    valid = np.isfinite(src_v_flat)
    if not valid.any():
        return np.zeros((nrow, ncol), dtype=float)
    pts = np.column_stack([src_x_flat[valid], src_y_flat[valid]])
    vals = src_v_flat[valid]

    if method == "idw":
        return _idw_interpolation(pts, vals, target_x, target_y, nrow, ncol, power=idw_power)
    return _griddata_interpolation(pts, vals, target_x, target_y, nrow, ncol, method=method)


def interpolate_points_to_grid(
    point_x: np.ndarray,
    point_y: np.ndarray,
    point_values: np.ndarray,
    target_x: np.ndarray,
    target_y: np.ndarray,
    nrow: int,
    ncol: int,
    method: InterpolationMethod = "nearest",
    *,
    idw_power: float = 2.0,
) -> np.ndarray:
    """Interpolate scattered point observations onto a (nrow, ncol) grid.

    Thin wrapper around :func:`interpolate_to_grid` for 1-D point arrays.
    """
    point_x = np.asarray(point_x, dtype=float).ravel()
    point_y = np.asarray(point_y, dtype=float).ravel()
    point_values = np.asarray(point_values, dtype=float).ravel()

    valid = np.isfinite(point_values)
    if not valid.any():
        return np.zeros((nrow, ncol), dtype=float)

    pts = np.column_stack([point_x[valid], point_y[valid]])
    vals = point_values[valid]

    if method == "idw":
        return _idw_interpolation(pts, vals, target_x, target_y, nrow, ncol, power=idw_power)
    return _griddata_interpolation(pts, vals, target_x, target_y, nrow, ncol, method=method)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _grids_are_aligned(
    source_values: np.ndarray,
    source_x: np.ndarray,
    source_y: np.ndarray,
    target_x: np.ndarray,
    target_y: np.ndarray,
    nrow: int,
    ncol: int,
) -> bool:
    """Return True when source and target grids are identical."""
    if source_values.shape != (nrow, ncol):
        return False
    if source_x.ndim != 1 or source_x.shape != (ncol,):
        return False
    if source_y.ndim != 1 or source_y.shape != (nrow,):
        return False
    tx = target_x[0, :] if target_x.ndim == 2 else target_x
    ty = target_y[:, 0] if target_y.ndim == 2 else target_y
    if tx.size != ncol or ty.size != nrow:
        return False
    return bool(np.allclose(source_x, tx, rtol=1e-6) and np.allclose(source_y, ty, rtol=1e-6))


def _flatten_source(
    source_values: np.ndarray,
    source_x: np.ndarray,
    source_y: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Flatten source arrays to 1-D coordinate + value arrays."""
    if source_x.ndim == 1 and source_y.ndim == 1:
        sx, sy = np.meshgrid(source_x, source_y, indexing="xy")
    elif source_x.ndim == 2 and source_y.ndim == 2:
        sx, sy = source_x, source_y
    else:
        return np.array([]), np.array([]), None
    return sx.ravel(), sy.ravel(), source_values.ravel()


def _griddata_interpolation(
    points: np.ndarray,
    values: np.ndarray,
    target_x: np.ndarray,
    target_y: np.ndarray,
    nrow: int,
    ncol: int,
    method: str,
) -> np.ndarray:
    """Interpolate using scipy.interpolate.griddata."""
    try:
        from scipy.interpolate import griddata

        result = griddata(points, values, (target_x, target_y), method=method)
        result = np.asarray(result, dtype=float).reshape(nrow, ncol)
        # Fill NaN with nearest for linear/cubic methods.
        if method != "nearest" and np.any(np.isnan(result)):
            nearest = griddata(points, values, (target_x, target_y), method="nearest")
            nearest = np.asarray(nearest, dtype=float).reshape(nrow, ncol)
            result = np.where(np.isnan(result), nearest, result)
        result = np.nan_to_num(result, nan=0.0)
        return result
    except ImportError:
        logger.warning("scipy not available; using uniform mean for interpolation.")
        return np.full((nrow, ncol), float(np.nanmean(values)), dtype=float)


def _idw_interpolation(
    points: np.ndarray,
    values: np.ndarray,
    target_x: np.ndarray,
    target_y: np.ndarray,
    nrow: int,
    ncol: int,
    power: float = 2.0,
) -> np.ndarray:
    """Inverse distance weighting interpolation.

    Uses scipy.spatial.cKDTree for efficient neighbor lookup.
    Falls back to brute-force computation when scipy is unavailable.
    """
    target_pts = np.column_stack([target_x.ravel(), target_y.ravel()])

    try:
        from scipy.spatial import cKDTree

        tree = cKDTree(points)
        # Query all source points; use at most k=min(len(points), 16).
        k = min(len(points), 16)
        distances, indices = tree.query(target_pts, k=k)
        if k == 1:
            distances = distances.reshape(-1, 1)
            indices = indices.reshape(-1, 1)

        # Handle coincident points (distance = 0) without evaluating the
        # singular branch on zero distances, which would emit a spurious
        # RuntimeWarning even though exact matches are treated separately below.
        weights = np.zeros_like(distances, dtype=float)
        positive_distances = distances > 0
        np.divide(
            1.0,
            np.power(distances, power),
            out=weights,
            where=positive_distances,
        )
        exact_match = distances == 0.0
        has_exact = np.any(exact_match, axis=1)

        result = np.zeros(len(target_pts), dtype=float)
        # Regular IDW for points without exact matches.
        regular = ~has_exact
        if regular.any():
            w = weights[regular]
            v = values[indices[regular]]
            result[regular] = np.sum(w * v, axis=1) / np.sum(w, axis=1)
        # Exact matches: use the value of the nearest coincident point.
        if has_exact.any():
            first_exact = np.argmax(exact_match[has_exact], axis=1)
            exact_indices = indices[has_exact][np.arange(first_exact.size), first_exact]
            result[has_exact] = values[exact_indices]

        return result.reshape(nrow, ncol)

    except ImportError:
        logger.warning("scipy not available; using brute-force IDW.")
        return _idw_brute_force(points, values, target_pts, nrow, ncol, power)


def _idw_brute_force(
    points: np.ndarray,
    values: np.ndarray,
    target_pts: np.ndarray,
    nrow: int,
    ncol: int,
    power: float,
) -> np.ndarray:
    """Brute-force IDW when scipy is unavailable."""
    result = np.zeros(len(target_pts), dtype=float)
    for i, tp in enumerate(target_pts):
        dists = np.sqrt(np.sum((points - tp) ** 2, axis=1))
        exact = dists == 0.0
        if np.any(exact):
            result[i] = values[exact][0]
        else:
            w = 1.0 / np.power(dists, power)
            result[i] = np.sum(w * values) / np.sum(w)
    return result.reshape(nrow, ncol)
