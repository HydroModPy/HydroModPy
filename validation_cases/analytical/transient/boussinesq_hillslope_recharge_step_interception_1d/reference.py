"""Approximate analytical references for transient hillslope interception."""

from __future__ import annotations

import numpy as np

from validation_cases.analytical.transient.linearized_unconfined_1d import (
    SECONDS_PER_DAY,
    mm_day_to_m_s,
)


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


def expected_linearized_hillslope_recharge_step_profiles(
    *,
    x_m: np.ndarray,
    eval_times_seconds,
    xmin: float,
    xmax: float,
    base_head_m: float,
    recharge_mm_day: float,
    hydraulic_conductivity_m_per_s: float,
    reference_saturated_thickness_m: float,
    specific_yield: float,
    n_terms: int = 400,
) -> np.ndarray:
    """Return the linearized recharge-step response for west divide / east fixed head."""
    x = np.asarray(x_m, dtype=float).reshape(-1)
    times = np.asarray(eval_times_seconds, dtype=float).reshape(-1)
    length = float(xmax) - float(xmin)
    if length <= 0.0:
        raise ValueError("xmax must be strictly larger than xmin.")
    if float(hydraulic_conductivity_m_per_s) <= 0.0:
        raise ValueError("hydraulic_conductivity_m_per_s must be > 0.")
    if float(reference_saturated_thickness_m) <= 0.0:
        raise ValueError("reference_saturated_thickness_m must be > 0.")
    if float(specific_yield) <= 0.0:
        raise ValueError("specific_yield must be > 0.")

    x_local = np.asarray(x - float(xmin), dtype=float)
    recharge_m_per_s = mm_day_to_m_s(float(recharge_mm_day))
    transmissivity = float(hydraulic_conductivity_m_per_s) * float(reference_saturated_thickness_m)
    diffusivity = transmissivity / float(specific_yield)

    eta_steady = (recharge_m_per_s / (2.0 * transmissivity)) * (length**2 - x_local**2)
    harmonics = np.arange(int(n_terms), dtype=float)
    wave_numbers = ((harmonics + 0.5) * np.pi) / length
    coefficients = (
        -2.0
        * recharge_m_per_s
        * (length**2)
        * ((-1.0) ** harmonics)
        / (transmissivity * ((harmonics + 0.5) ** 3) * (np.pi**3))
    )
    cosine_terms = np.cos(np.outer(wave_numbers, x_local))
    decay_terms = np.exp(-diffusivity * np.outer(times, wave_numbers**2))
    eta_transient = decay_terms @ (coefficients[:, None] * cosine_terms)
    return float(base_head_m) + eta_steady[None, :] + eta_transient


def resolve_toe_side_contact_start_x(
    *,
    x_m: np.ndarray,
    clearance_m: np.ndarray,
    contact_tolerance_m: float,
) -> float:
    """Return the inland start of the toe-side contact block, or NaN when absent."""
    x = np.asarray(x_m, dtype=float).reshape(-1)
    clearance = np.asarray(clearance_m, dtype=float).reshape(-1)
    saturated = clearance >= -float(contact_tolerance_m)
    start_index = len(saturated)
    for idx in range(len(saturated) - 1, -1, -1):
        if saturated[idx]:
            start_index = idx
        elif start_index < len(saturated):
            break
    if start_index >= len(saturated):
        return float("nan")
    return float(x[start_index])


def build_interception_trajectory_from_profiles(
    *,
    x_m: np.ndarray,
    profiles_m: np.ndarray,
    topography_profile_m: np.ndarray,
    contact_tolerance_m: float,
) -> np.ndarray:
    """Return one toe-side interception trajectory extracted from profile snapshots."""
    x = np.asarray(x_m, dtype=float).reshape(-1)
    profiles = np.asarray(profiles_m, dtype=float)
    topography = np.asarray(topography_profile_m, dtype=float).reshape(-1)
    if profiles.ndim != 2:
        raise ValueError("profiles_m must be a 2D array [time, x].")
    if profiles.shape[1] != x.size or topography.size != x.size:
        raise ValueError("x/profile/topography dimensions are inconsistent.")

    trajectory = [
        resolve_toe_side_contact_start_x(
            x_m=x,
            clearance_m=profile - topography,
            contact_tolerance_m=float(contact_tolerance_m),
        )
        for profile in profiles
    ]
    return np.asarray(trajectory, dtype=float)


def first_inland_interception_time_seconds(
    *,
    interception_x_by_time_m: np.ndarray,
    elapsed_seconds: np.ndarray,
    inland_contact_threshold_x_m: float,
) -> float:
    """Return the first time where the contact block extends inland beyond the toe cell."""
    x_traj = np.asarray(interception_x_by_time_m, dtype=float).reshape(-1)
    times = np.asarray(elapsed_seconds, dtype=float).reshape(-1)
    if x_traj.shape != times.shape:
        raise ValueError("interception_x_by_time_m and elapsed_seconds must share one shape.")

    inland_mask = np.isfinite(x_traj) & (x_traj <= float(inland_contact_threshold_x_m))
    if not np.any(inland_mask):
        return float("nan")
    return float(times[np.where(inland_mask)[0][0]])


__all__ = [
    "SECONDS_PER_DAY",
    "build_hillslope_topography_values",
    "build_interception_trajectory_from_profiles",
    "expected_linearized_hillslope_recharge_step_profiles",
    "first_inland_interception_time_seconds",
    "resolve_toe_side_contact_start_x",
]
