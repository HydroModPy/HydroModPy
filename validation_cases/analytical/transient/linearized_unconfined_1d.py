"""Shared analytical references for 1D linearized unconfined transient flow."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SECONDS_PER_DAY = 86400.0
MM_PER_M = 1000.0


def mm_day_to_m_s(value: float) -> float:
    """Convert one recharge rate from mm/day to m/s."""
    return float(value) / MM_PER_M / SECONDS_PER_DAY


def build_profile_x(*, xmin: float, xmax: float, ncol: int) -> np.ndarray:
    """Return the 1D profile support used by validation comparisons."""
    return np.linspace(float(xmin), float(xmax), int(ncol), dtype=float)


@dataclass(frozen=True, slots=True)
class LinearizedUnconfinedProperties:
    """Hydraulic coefficients of the linearized unconfined 1D model."""

    hydraulic_conductivity_m_per_s: float
    reference_saturated_thickness_m: float
    specific_yield: float

    @property
    def transmissivity_m2_per_s(self) -> float:
        return float(self.hydraulic_conductivity_m_per_s) * float(
            self.reference_saturated_thickness_m
        )

    @property
    def diffusivity_m2_per_s(self) -> float:
        return self.transmissivity_m2_per_s / float(self.specific_yield)


def _as_1d_seconds(times_seconds) -> np.ndarray:
    out = np.asarray(times_seconds, dtype=float).reshape(-1)
    if out.size == 0:
        raise ValueError("times_seconds cannot be empty.")
    return out


def boundary_step_response(
    *,
    x: np.ndarray,
    times_seconds,
    length_m: float,
    diffusivity_m2_per_s: float,
    n_terms: int = 400,
) -> np.ndarray:
    """Return the unit west-boundary step response with east boundary fixed to zero."""
    x_arr = np.asarray(x, dtype=float).reshape(-1)
    t_arr = _as_1d_seconds(times_seconds)
    length = float(length_m)
    diffusivity = float(diffusivity_m2_per_s)

    harmonics = np.arange(1, int(n_terms) + 1, dtype=float)
    wave_numbers = harmonics * np.pi / length
    exp_terms = np.exp(-diffusivity * np.outer(t_arr, wave_numbers**2))
    sin_terms = np.sin(np.outer(x_arr, wave_numbers))
    series = exp_terms @ (sin_terms / harmonics).T
    response = (1.0 - (x_arr / length))[None, :] - ((2.0 / np.pi) * series)
    return np.asarray(response, dtype=float)


def recharge_step_response(
    *,
    x: np.ndarray,
    times_seconds,
    length_m: float,
    transmissivity_m2_per_s: float,
    diffusivity_m2_per_s: float,
    n_terms: int = 400,
) -> np.ndarray:
    """Return the unit-recharge step response under fixed equal heads."""
    x_arr = np.asarray(x, dtype=float).reshape(-1)
    t_arr = _as_1d_seconds(times_seconds)
    length = float(length_m)
    transmissivity = float(transmissivity_m2_per_s)
    diffusivity = float(diffusivity_m2_per_s)

    odd_terms = (2.0 * np.arange(int(n_terms), dtype=float)) + 1.0
    wave_numbers = odd_terms * np.pi / length
    exp_terms = np.exp(-diffusivity * np.outer(t_arr, wave_numbers**2))
    sin_terms = np.sin(np.outer(x_arr, wave_numbers))
    series = exp_terms @ (sin_terms / (odd_terms**3)).T
    steady = (x_arr * (length - x_arr)) / (2.0 * transmissivity)
    transient = (4.0 * (length**2) / (transmissivity * (np.pi**3))) * series
    response = steady[None, :] - transient
    return np.asarray(response, dtype=float)


def _piecewise_level_at_eval_times(
    *,
    period_start_seconds: np.ndarray,
    period_levels: np.ndarray,
    eval_times_seconds: np.ndarray,
) -> np.ndarray:
    """Return the active piecewise-constant level at each solver output time."""
    indices = np.searchsorted(period_start_seconds, eval_times_seconds, side="left") - 1
    indices = np.clip(indices, 0, len(period_levels) - 1)
    return np.asarray(period_levels[indices], dtype=float)


def superpose_piecewise_steps(
    *,
    base_profile: float | np.ndarray,
    period_start_seconds,
    eval_times_seconds,
    period_levels,
    step_response_builder,
) -> np.ndarray:
    """Superpose one piecewise-constant forcing as a sum of analytical steps."""
    start_times = np.asarray(period_start_seconds, dtype=float).reshape(-1)
    eval_times = _as_1d_seconds(eval_times_seconds)
    levels = np.asarray(period_levels, dtype=float).reshape(-1)
    if start_times.shape != levels.shape:
        raise ValueError("period_start_seconds and period_levels must have the same length.")

    response = np.asarray(base_profile, dtype=float)
    if response.ndim == 0:
        response = np.full((eval_times.size, 1), float(response), dtype=float)
    else:
        response = np.broadcast_to(response, (eval_times.size, response.size)).copy()

    previous_level = 0.0
    for index, (change_time, level) in enumerate(zip(start_times, levels, strict=False)):
        jump = float(level) - float(previous_level)
        previous_level = float(level)
        if np.isclose(jump, 0.0):
            continue

        tau = eval_times - float(change_time)
        if index == 0 and np.isclose(change_time, 0.0):
            active = tau >= 0.0
        else:
            active = tau > 0.0
        if not np.any(active):
            continue

        response[active] += float(jump) * step_response_builder(tau[active])
    return np.asarray(response, dtype=float)


def west_boundary_profiles_from_period_levels(
    *,
    x: np.ndarray,
    eval_times_seconds,
    period_start_seconds,
    west_head_levels_m,
    base_head_m: float,
    properties: LinearizedUnconfinedProperties,
    n_terms: int = 400,
) -> np.ndarray:
    """Return absolute head profiles for a piecewise-constant west boundary series."""
    x_arr = np.asarray(x, dtype=float).reshape(-1)
    eval_times = _as_1d_seconds(eval_times_seconds)
    start_times = np.asarray(period_start_seconds, dtype=float).reshape(-1)
    west_levels = np.asarray(west_head_levels_m, dtype=float).reshape(-1)
    perturbation_levels = west_levels - float(base_head_m)

    profiles = superpose_piecewise_steps(
        base_profile=np.full(x_arr.size, float(base_head_m), dtype=float),
        period_start_seconds=start_times,
        eval_times_seconds=eval_times,
        period_levels=perturbation_levels,
        step_response_builder=lambda tau: boundary_step_response(
            x=x_arr,
            times_seconds=tau,
            length_m=float(x_arr[-1] - x_arr[0]),
            diffusivity_m2_per_s=properties.diffusivity_m2_per_s,
            n_terms=n_terms,
        ),
    )

    active_west = _piecewise_level_at_eval_times(
        period_start_seconds=start_times,
        period_levels=west_levels,
        eval_times_seconds=eval_times,
    )
    profiles[:, 0] = active_west
    profiles[:, -1] = float(base_head_m)
    return np.asarray(profiles, dtype=float)


def recharge_profiles_from_period_levels(
    *,
    x: np.ndarray,
    eval_times_seconds,
    period_start_seconds,
    recharge_levels_m_per_s,
    base_head_m: float,
    properties: LinearizedUnconfinedProperties,
    n_terms: int = 400,
) -> np.ndarray:
    """Return absolute head profiles for a piecewise-constant recharge series."""
    x_arr = np.asarray(x, dtype=float).reshape(-1)
    eval_times = _as_1d_seconds(eval_times_seconds)
    start_times = np.asarray(period_start_seconds, dtype=float).reshape(-1)
    recharge_levels = np.asarray(recharge_levels_m_per_s, dtype=float).reshape(-1)

    profiles = superpose_piecewise_steps(
        base_profile=np.full(x_arr.size, float(base_head_m), dtype=float),
        period_start_seconds=start_times,
        eval_times_seconds=eval_times,
        period_levels=recharge_levels,
        step_response_builder=lambda tau: recharge_step_response(
            x=x_arr,
            times_seconds=tau,
            length_m=float(x_arr[-1] - x_arr[0]),
            transmissivity_m2_per_s=properties.transmissivity_m2_per_s,
            diffusivity_m2_per_s=properties.diffusivity_m2_per_s,
            n_terms=n_terms,
        ),
    )
    profiles[:, 0] = float(base_head_m)
    profiles[:, -1] = float(base_head_m)
    return np.asarray(profiles, dtype=float)
