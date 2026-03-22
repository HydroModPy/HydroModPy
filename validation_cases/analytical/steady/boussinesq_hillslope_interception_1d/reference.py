"""Analytical helpers for the steady Boussinesq hillslope-interception case."""

from __future__ import annotations

import numpy as np


def build_hillslope_topography_values(
    *,
    x_m: np.ndarray,
    xmin: float,
    xmax: float,
    toe_elevation_m: float,
    slope_m_per_m: float,
) -> np.ndarray:
    """Return one linear hillslope topography descending toward the outlet."""
    x = np.asarray(x_m, dtype=float)
    return float(toe_elevation_m) + float(slope_m_per_m) * (float(xmax) - x)


def expected_boussinesq_hillslope_profile_at_x(
    *,
    x_m: np.ndarray,
    xmin: float,
    xmax: float,
    east_head_m: float,
    recharge_mm_day: float,
    hydraulic_conductivity_m_per_s: float,
) -> np.ndarray:
    """Return the exact 1D recharge profile with west divide and east fixed head."""
    x = np.asarray(x_m, dtype=float)
    length = float(xmax) - float(xmin)
    if length <= 0.0:
        raise ValueError("xmax must be strictly larger than xmin.")
    if float(hydraulic_conductivity_m_per_s) <= 0.0:
        raise ValueError("hydraulic_conductivity_m_per_s must be > 0.")

    x_local = x - float(xmin)
    recharge_m_per_s = float(recharge_mm_day) / 1000.0 / 86400.0
    alpha = recharge_m_per_s / float(hydraulic_conductivity_m_per_s)
    squared_head = float(east_head_m) ** 2 + alpha * (length**2 - x_local**2)
    return np.sqrt(np.maximum(squared_head, 0.0))


def find_boussinesq_hillslope_interception_x(
    *,
    xmin: float,
    xmax: float,
    east_head_m: float,
    recharge_mm_day: float,
    hydraulic_conductivity_m_per_s: float,
    toe_elevation_m: float,
    slope_m_per_m: float,
    search_samples: int = 20001,
) -> float:
    """Return the inland interception point where the analytical profile meets topography."""
    if int(search_samples) < 3:
        raise ValueError("search_samples must be >= 3.")

    x = np.linspace(float(xmin), float(xmax), int(search_samples), dtype=float)
    analytical = expected_boussinesq_hillslope_profile_at_x(
        x_m=x,
        xmin=float(xmin),
        xmax=float(xmax),
        east_head_m=float(east_head_m),
        recharge_mm_day=float(recharge_mm_day),
        hydraulic_conductivity_m_per_s=float(hydraulic_conductivity_m_per_s),
    )
    topography = build_hillslope_topography_values(
        x_m=x,
        xmin=float(xmin),
        xmax=float(xmax),
        toe_elevation_m=float(toe_elevation_m),
        slope_m_per_m=float(slope_m_per_m),
    )
    difference = analytical - topography
    sign_changes = np.where((difference[:-1] <= 0.0) & (difference[1:] > 0.0))[0]
    if sign_changes.size == 0:
        raise ValueError("No inland interception point found for the configured hillslope.")

    idx = int(sign_changes[0])
    x0 = float(x[idx])
    x1 = float(x[idx + 1])
    y0 = float(difference[idx])
    y1 = float(difference[idx + 1])
    if np.isclose(y1, y0):
        return x0
    return x0 - y0 * (x1 - x0) / (y1 - y0)
