"""Geometry helpers used by the Boussinesq solver mesh view."""

from __future__ import annotations

import numpy as np


def normalize_geom_type(raw_value: object) -> str:
    """Map bundle geometry aliases to the canonical token used by the solver."""
    token = str(raw_value).strip().lower()
    if token in {"triangle", "tri", "tri3"}:
        return "triangle"
    return token


def point_in_triangle(
    point_x_m: float,
    point_y_m: float,
    triangle_x_m: np.ndarray,
    triangle_y_m: np.ndarray,
    *,
    tolerance: float = 1.0e-12,
) -> bool:
    """Return True when one point lies inside or on the boundary of one triangle."""
    x0, x1, x2 = (float(value) for value in triangle_x_m)
    y0, y1, y2 = (float(value) for value in triangle_y_m)
    det = ((y1 - y2) * (x0 - x2)) + ((x2 - x1) * (y0 - y2))
    if abs(det) <= float(tolerance):
        return False

    l1 = (((y1 - y2) * (point_x_m - x2)) + ((x2 - x1) * (point_y_m - y2))) / det
    l2 = (((y2 - y0) * (point_x_m - x2)) + ((x0 - x2) * (point_y_m - y2))) / det
    l3 = 1.0 - l1 - l2
    return l1 >= -float(tolerance) and l2 >= -float(tolerance) and l3 >= -float(tolerance)


def optional_finite_float(value: float) -> float | None:
    """Convert one sampled float to the bundle optional-float convention."""
    if not np.isfinite(float(value)):
        return None
    return float(value)


def optional_finite_nanmean(values: np.ndarray) -> float | None:
    """Return one finite nanmean, or None when the sample contains no finite data."""
    array = np.asarray(values, dtype=float).reshape(-1)
    finite = np.isfinite(array)
    if not np.any(finite):
        return None
    return float(np.nanmean(array[finite]))


def polygon_area(vertices: np.ndarray) -> float:
    """Compute one polygon area from ordered XY vertices."""
    coords = np.asarray(vertices, dtype=float)
    x_vals = coords[:, 0]
    y_vals = coords[:, 1]
    return float(
        0.5 * abs(np.dot(x_vals, np.roll(y_vals, -1)) - np.dot(y_vals, np.roll(x_vals, -1)))
    )
