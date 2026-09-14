"""Closed-form seepage limit of a Dupuit hillslope draining at its surface.

Geometry: a plane surface ``z = slope * x`` over a flat substratum, ``x``
measured upslope from the toe where the surface meets the substratum. The
hillslope is closed at both ends: at ``x = L`` by the divide, at ``x = 0``
because the saturated thickness vanishes there.

Under Dupuit assumptions the aquifer carries at most ``K * slope**2 * x`` past
the position ``x`` while the recharge collected upslope of ``x`` is
``R * (L - x)``. Equating the two gives the seepage limit ``x_e``: below it the
water table is pinned at the surface and the excess leaves through the drains,
above it the water table sits strictly below the surface.
"""

from __future__ import annotations

import numpy as np

MM_PER_M = 1000.0
SECONDS_PER_DAY = 86400.0


def recharge_mm_day_to_m_per_s(value_mm_per_day: float) -> float:
    """Convert a recharge rate from mm/day to m/s."""
    return float(value_mm_per_day) / MM_PER_M / SECONDS_PER_DAY


def hillslope_slope(*, topography_profile: np.ndarray, cell_size_m: float) -> float:
    """Return the surface slope of a plane hillslope sampled at cell centers."""
    profile = np.asarray(topography_profile, dtype=float)
    if profile.size < 2:
        raise ValueError("topography_profile needs at least two columns.")
    if float(cell_size_m) <= 0.0:
        raise ValueError("cell_size_m must be > 0.")
    return float((profile[0] - profile[-1]) / ((profile.size - 1) * float(cell_size_m)))


def hillslope_coordinate_m(
    *,
    topography_profile: np.ndarray,
    slope: float,
    substratum_elevation_m: float,
) -> np.ndarray:
    """Return the distance from the toe for each column of a plane hillslope."""
    if float(slope) <= 0.0:
        raise ValueError("slope must be > 0.")
    profile = np.asarray(topography_profile, dtype=float)
    return (profile - float(substratum_elevation_m)) / float(slope)


def seepage_limit_position_m(
    *,
    hillslope_length_m: float,
    slope: float,
    hydraulic_conductivity_m_per_s: float,
    recharge_m_per_s: float,
) -> float:
    """Return ``x_e = L / (1 + slope**2 * K / R)``, the start of the seepage face.

    The result depends on ``K`` and ``R`` only through their ratio, which is the
    property the calibration relies on.
    """
    if float(hillslope_length_m) <= 0.0:
        raise ValueError("hillslope_length_m must be > 0.")
    if float(recharge_m_per_s) <= 0.0:
        raise ValueError("recharge_m_per_s must be > 0.")
    if float(hydraulic_conductivity_m_per_s) <= 0.0:
        raise ValueError("hydraulic_conductivity_m_per_s must be > 0.")
    ratio = float(hydraulic_conductivity_m_per_s) / float(recharge_m_per_s)
    return float(hillslope_length_m) / (1.0 + (float(slope) ** 2 * ratio))


def expected_head_profile_m(
    *,
    x_m: np.ndarray,
    hillslope_length_m: float,
    slope: float,
    hydraulic_conductivity_m_per_s: float,
    recharge_m_per_s: float,
    substratum_elevation_m: float,
) -> np.ndarray:
    """Return the steady Dupuit water table of the seeping hillslope.

    Below ``x_e`` the water table follows the surface. Above it the profile is
    the free Dupuit solution that leaves the surface tangentially at ``x_e``.
    """
    x = np.asarray(x_m, dtype=float)
    limit = seepage_limit_position_m(
        hillslope_length_m=float(hillslope_length_m),
        slope=float(slope),
        hydraulic_conductivity_m_per_s=float(hydraulic_conductivity_m_per_s),
        recharge_m_per_s=float(recharge_m_per_s),
    )
    recharge_ratio = float(recharge_m_per_s) / float(hydraulic_conductivity_m_per_s)
    free_squared = (float(slope) * limit) ** 2 + 2.0 * recharge_ratio * (
        float(hillslope_length_m) * (x - limit) - 0.5 * (x**2 - limit**2)
    )
    free = np.sqrt(np.maximum(free_squared, 0.0))
    return float(substratum_elevation_m) + np.where(x <= limit, float(slope) * x, free)


def expected_seepage_mask(*, x_m: np.ndarray, seepage_limit_m: float) -> np.ndarray:
    """Return the analytical seepage mask: True below the seepage limit."""
    return np.asarray(x_m, dtype=float) <= float(seepage_limit_m)


__all__ = [
    "expected_head_profile_m",
    "expected_seepage_mask",
    "hillslope_coordinate_m",
    "hillslope_slope",
    "recharge_mm_day_to_m_per_s",
    "seepage_limit_position_m",
]
