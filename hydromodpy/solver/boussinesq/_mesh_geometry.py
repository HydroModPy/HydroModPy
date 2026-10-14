"""Geometry helpers used by the Boussinesq solver mesh view."""

from __future__ import annotations

import numpy as np


def normalize_geom_type(raw_value: object) -> str:
    """Map bundle geometry aliases to the canonical token used by the solver."""
    token = str(raw_value).strip().lower()
    if token in {"triangle", "tri", "tri3"}:
        return "triangle"
    return token


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
