"""Analytical helpers for the steady Boussinesq hillslope-interception case.

The water table of a recharged hillslope that drains to its toe meets the land
surface and seeps out over a lower part of the slope. Under Dupuit, with a flat
bottom ``z_b``, a linear surface of slope ``S`` and the outlet head at the toe
elevation, the steady free-boundary problem has a closed form. Over the seepage
face the head is the surface and the aquifer carries ``q = K S (z_top - z_b)``.
Upslope of the emergence point ``x_e`` all the recharge passes through:
``q = R (x - x_min)``. The flux is continuous at ``x_e``:

``R (x_e - x_min) = K S (z_top(x_e) - z_b)``

and the dry profile meets the surface tangentially there:

``(h - z_b)^2 = (z_top(x_e) - z_b)^2 + (R / K) ((x_e - x_min)^2 - (x - x_min)^2)``.
"""

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


def hillslope_seepage_emergence_x(
    *,
    xmin: float,
    xmax: float,
    toe_elevation_m: float,
    slope_m_per_m: float,
    bottom_elevation_m: float,
    recharge_mm_day: float,
    hydraulic_conductivity_m_per_s: float,
) -> float:
    """Return the emergence point ``x_e`` of the seepage face."""
    recharge_m_s = float(recharge_mm_day) / 1000.0 / 86400.0
    k_s = float(hydraulic_conductivity_m_per_s) * float(slope_m_per_m)
    thickness_at_divide_m = (
        float(toe_elevation_m) - float(bottom_elevation_m) + float(slope_m_per_m) * float(xmax)
    )
    x_e = (k_s * thickness_at_divide_m + recharge_m_s * float(xmin)) / (
        recharge_m_s + k_s * float(slope_m_per_m)
    )
    if not float(xmin) < x_e < float(xmax):
        raise ValueError("The water table does not reach the surface inside the hillslope.")
    return float(x_e)


def expected_hillslope_seepage_profile_at_x(
    *,
    x_m: np.ndarray,
    xmin: float,
    xmax: float,
    east_head_m: float,
    toe_elevation_m: float,
    slope_m_per_m: float,
    bottom_elevation_m: float,
    recharge_mm_day: float,
    hydraulic_conductivity_m_per_s: float,
) -> np.ndarray:
    """Return the exact steady head with a seepage face below the emergence point."""
    if not np.isclose(float(east_head_m), float(toe_elevation_m)):
        raise ValueError("The closed form needs the outlet head at the toe elevation.")
    x = np.asarray(x_m, dtype=float)
    x_e = hillslope_seepage_emergence_x(
        xmin=xmin,
        xmax=xmax,
        toe_elevation_m=toe_elevation_m,
        slope_m_per_m=slope_m_per_m,
        bottom_elevation_m=bottom_elevation_m,
        recharge_mm_day=recharge_mm_day,
        hydraulic_conductivity_m_per_s=hydraulic_conductivity_m_per_s,
    )
    top = build_hillslope_topography_values(
        x_m=x, xmin=xmin, xmax=xmax, toe_elevation_m=toe_elevation_m, slope_m_per_m=slope_m_per_m
    )
    thickness_e_m = (float(toe_elevation_m) + float(slope_m_per_m) * (float(xmax) - x_e)) - float(
        bottom_elevation_m
    )
    alpha = float(recharge_mm_day) / 1000.0 / 86400.0 / float(hydraulic_conductivity_m_per_s)
    squared = thickness_e_m**2 + alpha * ((x_e - float(xmin)) ** 2 - (x - float(xmin)) ** 2)
    dry = float(bottom_elevation_m) + np.sqrt(np.maximum(squared, 0.0))
    return np.where(x < x_e, dry, top)


def hillslope_contact_x(
    *,
    contact_tolerance_m: float,
    search_samples: int = 20001,
    **profile_kwargs: float,
) -> float:
    """Return the first ``x`` where the exact head comes within the tolerance of the surface.

    The dry profile meets the surface tangentially, so a contact read with a
    tolerance of a few centimetres starts tens of metres upslope of ``x_e``.
    The model is read with the same tolerance.
    """
    if int(search_samples) < 3:
        raise ValueError("search_samples must be >= 3.")
    x = np.linspace(
        float(profile_kwargs["xmin"]), float(profile_kwargs["xmax"]), int(search_samples)
    )
    head = expected_hillslope_seepage_profile_at_x(x_m=x, **profile_kwargs)
    top = build_hillslope_topography_values(
        x_m=x,
        xmin=profile_kwargs["xmin"],
        xmax=profile_kwargs["xmax"],
        toe_elevation_m=profile_kwargs["toe_elevation_m"],
        slope_m_per_m=profile_kwargs["slope_m_per_m"],
    )
    within = np.flatnonzero(top - head <= float(contact_tolerance_m))
    if within.size == 0:
        raise ValueError("The exact profile never comes within the contact tolerance.")
    return float(x[int(within[0])])


__all__ = [
    "build_hillslope_topography_values",
    "expected_hillslope_seepage_profile_at_x",
    "hillslope_contact_x",
    "hillslope_seepage_emergence_x",
]
