"""Analytical helpers for steady 1D Boussinesq cases on a sloping substratum."""

from __future__ import annotations

import numpy as np


def build_uniform_cell_center_x_values(
    *,
    xmin: float,
    xmax: float,
    ncol: int,
) -> np.ndarray:
    """Return the uniform cell-center abscissas used by 1D strip benchmarks."""
    length = float(xmax) - float(xmin)
    if length <= 0.0:
        raise ValueError("xmax must be strictly larger than xmin.")
    if int(ncol) <= 0:
        raise ValueError("ncol must be > 0.")

    dx = length / float(ncol)
    return float(xmin) + ((np.arange(int(ncol), dtype=float) + 0.5) * dx)


def build_validation_profile_x_values(
    *,
    xmin: float,
    xmax: float,
    ncol: int,
    solver_name: str | None,
) -> np.ndarray:
    """Return the x support that matches one validation backend output.

    Launcher-backed MODFLOW profiles are sampled on the full strip support,
    whereas the local Boussinesq strip runtime is exported on structured bins
    built from triangle centroids and therefore aligns with cell centers.
    """
    normalized_solver = "" if solver_name is None else str(solver_name).strip().lower()
    if normalized_solver == "boussinesq":
        return build_uniform_cell_center_x_values(
            xmin=float(xmin),
            xmax=float(xmax),
            ncol=int(ncol),
        )
    return np.linspace(float(xmin), float(xmax), int(ncol), dtype=float)


def build_linear_surface_values(
    *,
    x_m: np.ndarray,
    xmin: float,
    xmax: float,
    base_elevation_m: float,
    right_to_left_amplitude_m: float,
) -> np.ndarray:
    """Return one linear profile sampled at explicit x positions."""
    length = float(xmax) - float(xmin)
    if length <= 0.0:
        raise ValueError("xmax must be strictly larger than xmin.")

    x = np.asarray(x_m, dtype=float)
    x_local = x - float(xmin)
    return float(base_elevation_m) + float(right_to_left_amplitude_m) * (
        1.0 - (x_local / length)
    )


def build_linear_substratum_values(
    *,
    x_m: np.ndarray,
    xmin: float,
    xmax: float,
    bottom_base_elevation_m: float,
    bottom_right_to_left_amplitude_m: float,
) -> np.ndarray:
    """Return the impermeable-bottom elevation along one sloping strip."""
    return build_linear_surface_values(
        x_m=x_m,
        xmin=float(xmin),
        xmax=float(xmax),
        base_elevation_m=float(bottom_base_elevation_m),
        right_to_left_amplitude_m=float(bottom_right_to_left_amplitude_m),
    )


def build_linear_topography_values(
    *,
    x_m: np.ndarray,
    xmin: float,
    xmax: float,
    topography_base_elevation_m: float,
    topography_right_to_left_amplitude_m: float,
) -> np.ndarray:
    """Return the land-surface elevation along one linear hillslope."""
    return build_linear_surface_values(
        x_m=x_m,
        xmin=float(xmin),
        xmax=float(xmax),
        base_elevation_m=float(topography_base_elevation_m),
        right_to_left_amplitude_m=float(topography_right_to_left_amplitude_m),
    )


def _mm_day_to_m_s(recharge_mm_day: float) -> float:
    """Convert one recharge rate from mm/day to m/s."""
    return float(recharge_mm_day) * 1.0e-3 / 86400.0


def expected_sloping_substratum_constant_thickness_profile_at_x(
    *,
    x_m: np.ndarray,
    xmin: float,
    xmax: float,
    bottom_base_elevation_m: float,
    bottom_right_to_left_amplitude_m: float,
    saturated_thickness_m: float,
) -> np.ndarray:
    """Return the exact steady head for one constant-thickness sloping case."""
    bottom = build_linear_substratum_values(
        x_m=np.asarray(x_m, dtype=float),
        xmin=float(xmin),
        xmax=float(xmax),
        bottom_base_elevation_m=float(bottom_base_elevation_m),
        bottom_right_to_left_amplitude_m=float(bottom_right_to_left_amplitude_m),
    )
    if float(saturated_thickness_m) <= 0.0:
        raise ValueError("saturated_thickness_m must be > 0.")
    return bottom + float(saturated_thickness_m)


def expected_sloping_substratum_constant_thickness_profile(
    *,
    xmin: float,
    xmax: float,
    ncol: int,
    bottom_base_elevation_m: float,
    bottom_right_to_left_amplitude_m: float,
    saturated_thickness_m: float,
) -> np.ndarray:
    """Return the exact steady head on one uniform cell-center support."""
    x = build_uniform_cell_center_x_values(
        xmin=float(xmin),
        xmax=float(xmax),
        ncol=int(ncol),
    )
    return expected_sloping_substratum_constant_thickness_profile_at_x(
        x_m=x,
        xmin=float(xmin),
        xmax=float(xmax),
        bottom_base_elevation_m=float(bottom_base_elevation_m),
        bottom_right_to_left_amplitude_m=float(bottom_right_to_left_amplitude_m),
        saturated_thickness_m=float(saturated_thickness_m),
    )


def _sloping_substratum_length_from_discharge(
    *,
    discharge_per_width_m2_s: float,
    west_saturated_thickness_m: float,
    east_saturated_thickness_m: float,
    hydraulic_conductivity_m_per_s: float,
    bottom_slope_m_per_m: float,
) -> float:
    """Return the implicit-profile length associated with one discharge value."""
    conductivity = float(hydraulic_conductivity_m_per_s)
    slope = float(bottom_slope_m_per_m)
    if conductivity <= 0.0:
        raise ValueError("hydraulic_conductivity_m_per_s must be > 0.")
    if slope <= 0.0:
        raise ValueError("bottom_slope_m_per_m must be > 0.")

    alpha = conductivity * slope
    discharge = float(discharge_per_width_m2_s)
    west_term = alpha * float(west_saturated_thickness_m) - discharge
    east_term = alpha * float(east_saturated_thickness_m) - discharge
    singular_scale = max(
        abs(alpha * float(west_saturated_thickness_m)),
        abs(alpha * float(east_saturated_thickness_m)),
        abs(discharge),
        1.0,
    )
    singular_atol = np.finfo(float).eps * singular_scale * 32.0
    if abs(west_term) <= singular_atol or abs(east_term) <= singular_atol:
        raise ValueError("discharge_per_width_m2_s falls on the singular profile branch.")

    def _primitive(thickness_m: float) -> float:
        term = alpha * float(thickness_m) - discharge
        return (
            term + (discharge * np.log(abs(term)))
        ) / (conductivity * slope * slope)

    return float(
        _primitive(float(east_saturated_thickness_m))
        - _primitive(float(west_saturated_thickness_m))
    )


def solve_sloping_substratum_fixed_head_discharge_per_width(
    *,
    xmin: float,
    xmax: float,
    west_head_m: float,
    east_head_m: float,
    bottom_base_elevation_m: float,
    bottom_right_to_left_amplitude_m: float,
    hydraulic_conductivity_m_per_s: float,
) -> float:
    """Return the steady discharge per unit width for one sloping no-recharge strip.

    The current validation case uses one eastward-flow regime where the lateral
    discharge exceeds ``K * S0 * b`` along the whole strip, so the implicit
    profile remains on the same monotonic branch.
    """
    length = float(xmax) - float(xmin)
    if length <= 0.0:
        raise ValueError("xmax must be strictly larger than xmin.")
    conductivity = float(hydraulic_conductivity_m_per_s)
    if conductivity <= 0.0:
        raise ValueError("hydraulic_conductivity_m_per_s must be > 0.")

    bottom_boundary = build_linear_substratum_values(
        x_m=np.asarray([float(xmin), float(xmax)], dtype=float),
        xmin=float(xmin),
        xmax=float(xmax),
        bottom_base_elevation_m=float(bottom_base_elevation_m),
        bottom_right_to_left_amplitude_m=float(bottom_right_to_left_amplitude_m),
    )
    west_bottom_m = float(bottom_boundary[0])
    east_bottom_m = float(bottom_boundary[1])
    west_thickness_m = float(west_head_m) - west_bottom_m
    east_thickness_m = float(east_head_m) - east_bottom_m
    if west_thickness_m <= 0.0 or east_thickness_m <= 0.0:
        raise ValueError("Boundary heads must remain strictly above the local substratum.")

    slope = float(bottom_right_to_left_amplitude_m) / length
    alpha = conductivity * slope
    branch_floor = alpha * max(west_thickness_m, east_thickness_m)
    lo = branch_floor * (1.0 + 1.0e-6) + 1.0e-12
    hi = max(2.0 * lo, 1.0e-8)

    def _residual(discharge_m2_s: float) -> float:
        return _sloping_substratum_length_from_discharge(
            discharge_per_width_m2_s=float(discharge_m2_s),
            west_saturated_thickness_m=west_thickness_m,
            east_saturated_thickness_m=east_thickness_m,
            hydraulic_conductivity_m_per_s=conductivity,
            bottom_slope_m_per_m=slope,
        ) - length

    residual_lo = _residual(lo)
    residual_hi = _residual(hi)
    expansion_count = 0
    while residual_lo * residual_hi > 0.0:
        hi *= 2.0
        residual_hi = _residual(hi)
        expansion_count += 1
        if expansion_count > 80:
            raise RuntimeError(
                "Could not bracket the sloping-substratum discharge on the expected profile branch."
            )

    for _ in range(120):
        mid = 0.5 * (lo + hi)
        residual_mid = _residual(mid)
        if abs(residual_mid) <= 1.0e-12:
            return float(mid)
        if residual_lo * residual_mid <= 0.0:
            hi = mid
            residual_hi = residual_mid
        else:
            lo = mid
            residual_lo = residual_mid
    return float(0.5 * (lo + hi))


def expected_sloping_substratum_fixed_head_saturated_thickness_at_x(
    *,
    x_m: np.ndarray,
    xmin: float,
    xmax: float,
    west_head_m: float,
    east_head_m: float,
    bottom_base_elevation_m: float,
    bottom_right_to_left_amplitude_m: float,
    hydraulic_conductivity_m_per_s: float,
) -> np.ndarray:
    """Return the saturated-thickness profile for one sloping no-recharge strip."""
    length = float(xmax) - float(xmin)
    if length <= 0.0:
        raise ValueError("xmax must be strictly larger than xmin.")

    x = np.asarray(x_m, dtype=float)
    x_local = x - float(xmin)
    if np.any(x_local < -1.0e-12) or np.any(x_local > length + 1.0e-12):
        raise ValueError("x_m values must remain inside [xmin, xmax].")

    bottom_boundary = build_linear_substratum_values(
        x_m=np.asarray([float(xmin), float(xmax)], dtype=float),
        xmin=float(xmin),
        xmax=float(xmax),
        bottom_base_elevation_m=float(bottom_base_elevation_m),
        bottom_right_to_left_amplitude_m=float(bottom_right_to_left_amplitude_m),
    )
    west_bottom_m = float(bottom_boundary[0])
    east_bottom_m = float(bottom_boundary[1])
    west_thickness_m = float(west_head_m) - west_bottom_m
    east_thickness_m = float(east_head_m) - east_bottom_m
    if west_thickness_m <= 0.0 or east_thickness_m <= 0.0:
        raise ValueError("Boundary heads must remain strictly above the local substratum.")

    slope = float(bottom_right_to_left_amplitude_m) / length
    discharge = solve_sloping_substratum_fixed_head_discharge_per_width(
        xmin=float(xmin),
        xmax=float(xmax),
        west_head_m=float(west_head_m),
        east_head_m=float(east_head_m),
        bottom_base_elevation_m=float(bottom_base_elevation_m),
        bottom_right_to_left_amplitude_m=float(bottom_right_to_left_amplitude_m),
        hydraulic_conductivity_m_per_s=float(hydraulic_conductivity_m_per_s),
    )
    alpha = float(hydraulic_conductivity_m_per_s) * slope

    def _primitive(thickness_m: float) -> float:
        term = (alpha * float(thickness_m)) - discharge
        return (
            term + (discharge * np.log(abs(term)))
        ) / (float(hydraulic_conductivity_m_per_s) * slope * slope)

    thickness_min = min(west_thickness_m, east_thickness_m)
    thickness_max = max(west_thickness_m, east_thickness_m)
    primitive_min = _primitive(thickness_min)
    primitive_max = _primitive(thickness_max)
    increasing = primitive_max > primitive_min
    primitive_west = _primitive(west_thickness_m)

    profile = np.empty_like(x, dtype=float)
    for index, x_local_value in enumerate(x_local):
        target = primitive_west + float(x_local_value)
        lo = thickness_min
        hi = thickness_max
        for _ in range(120):
            mid = 0.5 * (lo + hi)
            primitive_mid = _primitive(mid)
            if abs(primitive_mid - target) <= 1.0e-12:
                lo = mid
                hi = mid
                break
            if (primitive_mid < target) == increasing:
                lo = mid
            else:
                hi = mid
        profile[index] = 0.5 * (lo + hi)
    return profile


def expected_sloping_substratum_fixed_head_profile_at_x(
    *,
    x_m: np.ndarray,
    xmin: float,
    xmax: float,
    west_head_m: float,
    east_head_m: float,
    bottom_base_elevation_m: float,
    bottom_right_to_left_amplitude_m: float,
    hydraulic_conductivity_m_per_s: float,
) -> np.ndarray:
    """Return the steady head profile for one sloping no-recharge strip."""
    bottom = build_linear_substratum_values(
        x_m=np.asarray(x_m, dtype=float),
        xmin=float(xmin),
        xmax=float(xmax),
        bottom_base_elevation_m=float(bottom_base_elevation_m),
        bottom_right_to_left_amplitude_m=float(bottom_right_to_left_amplitude_m),
    )
    thickness = expected_sloping_substratum_fixed_head_saturated_thickness_at_x(
        x_m=np.asarray(x_m, dtype=float),
        xmin=float(xmin),
        xmax=float(xmax),
        west_head_m=float(west_head_m),
        east_head_m=float(east_head_m),
        bottom_base_elevation_m=float(bottom_base_elevation_m),
        bottom_right_to_left_amplitude_m=float(bottom_right_to_left_amplitude_m),
        hydraulic_conductivity_m_per_s=float(hydraulic_conductivity_m_per_s),
    )
    return bottom + thickness


def expected_sloping_substratum_fixed_head_profile(
    *,
    xmin: float,
    xmax: float,
    ncol: int,
    west_head_m: float,
    east_head_m: float,
    bottom_base_elevation_m: float,
    bottom_right_to_left_amplitude_m: float,
    hydraulic_conductivity_m_per_s: float,
) -> np.ndarray:
    """Return the steady head profile on one uniform cell-center support."""
    x = build_uniform_cell_center_x_values(
        xmin=float(xmin),
        xmax=float(xmax),
        ncol=int(ncol),
    )
    return expected_sloping_substratum_fixed_head_profile_at_x(
        x_m=x,
        xmin=float(xmin),
        xmax=float(xmax),
        west_head_m=float(west_head_m),
        east_head_m=float(east_head_m),
        bottom_base_elevation_m=float(bottom_base_elevation_m),
        bottom_right_to_left_amplitude_m=float(bottom_right_to_left_amplitude_m),
        hydraulic_conductivity_m_per_s=float(hydraulic_conductivity_m_per_s),
    )


def _integrate_sloping_substratum_uniform_recharge_saturated_thickness(
    *,
    length_m: float,
    west_saturated_thickness_m: float,
    west_discharge_per_width_m2_s: float,
    hydraulic_conductivity_m_per_s: float,
    bottom_slope_m_per_m: float,
    recharge_m_per_s: float,
    n_steps: int = 4096,
) -> tuple[np.ndarray, np.ndarray, bool]:
    """Integrate the steady sloping-substratum profile for one west discharge.

    The governing steady 1D system is:

    ``dq/dx = R`` and ``db/dx = S0 - q/(K b)``,

    with ``q(x) = q_w + R (x - xmin)`` on one strip of unit width.
    """
    length = float(length_m)
    if length <= 0.0:
        raise ValueError("length_m must be > 0.")
    conductivity = float(hydraulic_conductivity_m_per_s)
    if conductivity <= 0.0:
        raise ValueError("hydraulic_conductivity_m_per_s must be > 0.")
    slope = float(bottom_slope_m_per_m)
    if slope <= 0.0:
        raise ValueError("bottom_slope_m_per_m must be > 0.")
    if float(n_steps) < 2:
        raise ValueError("n_steps must be >= 2.")

    recharge = float(recharge_m_per_s)
    west_discharge = float(west_discharge_per_width_m2_s)
    dx = length / float(int(n_steps))
    x_values = np.linspace(0.0, length, int(n_steps) + 1, dtype=float)
    thickness = np.empty(int(n_steps) + 1, dtype=float)
    thickness[0] = float(west_saturated_thickness_m)
    if thickness[0] <= 0.0:
        raise ValueError("west_saturated_thickness_m must be > 0.")

    min_thickness_m = 1.0e-10

    def _rhs(x_local_m: float, saturated_thickness_m: float) -> float:
        if float(saturated_thickness_m) <= min_thickness_m:
            return np.nan
        discharge = west_discharge + recharge * float(x_local_m)
        return slope - (discharge / (conductivity * float(saturated_thickness_m)))

    for index in range(int(n_steps)):
        x_local = float(x_values[index])
        current = float(thickness[index])
        k1 = _rhs(x_local, current)
        k2 = _rhs(x_local + 0.5 * dx, current + 0.5 * dx * k1)
        k3 = _rhs(x_local + 0.5 * dx, current + 0.5 * dx * k2)
        k4 = _rhs(x_local + dx, current + dx * k3)
        if not np.all(np.isfinite(np.asarray([k1, k2, k3, k4], dtype=float))):
            return x_values[: index + 1], thickness[: index + 1], False
        next_value = current + (dx / 6.0) * (k1 + (2.0 * k2) + (2.0 * k3) + k4)
        thickness[index + 1] = next_value
        if next_value <= min_thickness_m:
            return x_values[: index + 2], thickness[: index + 2], False

    return x_values, thickness, True


def solve_sloping_substratum_uniform_recharge_west_discharge_per_width(
    *,
    xmin: float,
    xmax: float,
    west_head_m: float,
    east_head_m: float,
    bottom_base_elevation_m: float,
    bottom_right_to_left_amplitude_m: float,
    hydraulic_conductivity_m_per_s: float,
    recharge_mm_day: float,
) -> float:
    """Return the steady west-boundary discharge for one recharge hillslope.

    The west discharge is obtained by shooting on the coupled steady system
    written on saturated thickness ``b`` and unit-width discharge ``q``:

    ``dq/dx = R`` and ``db/dx = S0 - q / (K b)``.
    """
    length = float(xmax) - float(xmin)
    if length <= 0.0:
        raise ValueError("xmax must be strictly larger than xmin.")
    conductivity = float(hydraulic_conductivity_m_per_s)
    if conductivity <= 0.0:
        raise ValueError("hydraulic_conductivity_m_per_s must be > 0.")
    recharge_m_per_s = _mm_day_to_m_s(float(recharge_mm_day))
    if recharge_m_per_s < 0.0:
        raise ValueError("recharge_mm_day must be >= 0.")

    bottom_boundary = build_linear_substratum_values(
        x_m=np.asarray([float(xmin), float(xmax)], dtype=float),
        xmin=float(xmin),
        xmax=float(xmax),
        bottom_base_elevation_m=float(bottom_base_elevation_m),
        bottom_right_to_left_amplitude_m=float(bottom_right_to_left_amplitude_m),
    )
    west_bottom_m = float(bottom_boundary[0])
    east_bottom_m = float(bottom_boundary[1])
    west_thickness_m = float(west_head_m) - west_bottom_m
    east_thickness_m = float(east_head_m) - east_bottom_m
    if west_thickness_m <= 0.0 or east_thickness_m <= 0.0:
        raise ValueError("Boundary heads must remain strictly above the local substratum.")

    slope = float(bottom_right_to_left_amplitude_m) / length
    no_recharge_discharge = solve_sloping_substratum_fixed_head_discharge_per_width(
        xmin=float(xmin),
        xmax=float(xmax),
        west_head_m=float(west_head_m),
        east_head_m=float(east_head_m),
        bottom_base_elevation_m=float(bottom_base_elevation_m),
        bottom_right_to_left_amplitude_m=float(bottom_right_to_left_amplitude_m),
        hydraulic_conductivity_m_per_s=conductivity,
    )
    center = float(no_recharge_discharge) - 0.5 * recharge_m_per_s * length
    flux_scale = max(
        abs(center),
        conductivity * slope * max(west_thickness_m, east_thickness_m),
        recharge_m_per_s * length,
        1.0e-8,
    )

    def _residual(west_discharge_m2_s: float) -> float:
        _, thickness, success = _integrate_sloping_substratum_uniform_recharge_saturated_thickness(
            length_m=length,
            west_saturated_thickness_m=west_thickness_m,
            west_discharge_per_width_m2_s=float(west_discharge_m2_s),
            hydraulic_conductivity_m_per_s=conductivity,
            bottom_slope_m_per_m=slope,
            recharge_m_per_s=recharge_m_per_s,
        )
        if not success:
            return -1.0e6
        return float(thickness[-1] - east_thickness_m)

    scale = flux_scale
    lo = center - scale
    hi = center + scale
    residual_lo = _residual(lo)
    residual_hi = _residual(hi)
    expansion_count = 0
    while residual_lo * residual_hi > 0.0:
        scale *= 2.0
        lo = center - scale
        hi = center + scale
        residual_lo = _residual(lo)
        residual_hi = _residual(hi)
        expansion_count += 1
        if expansion_count > 80:
            raise RuntimeError(
                "Could not bracket the sloping-substratum recharge discharge."
            )

    for _ in range(120):
        mid = 0.5 * (lo + hi)
        residual_mid = _residual(mid)
        if abs(residual_mid) <= 1.0e-12:
            return float(mid)
        if residual_lo * residual_mid <= 0.0:
            hi = mid
            residual_hi = residual_mid
        else:
            lo = mid
            residual_lo = residual_mid
    return float(0.5 * (lo + hi))


def expected_sloping_substratum_uniform_recharge_saturated_thickness_at_x(
    *,
    x_m: np.ndarray,
    xmin: float,
    xmax: float,
    west_head_m: float,
    east_head_m: float,
    bottom_base_elevation_m: float,
    bottom_right_to_left_amplitude_m: float,
    hydraulic_conductivity_m_per_s: float,
    recharge_mm_day: float,
) -> np.ndarray:
    """Return the saturated-thickness profile for one recharge hillslope."""
    length = float(xmax) - float(xmin)
    if length <= 0.0:
        raise ValueError("xmax must be strictly larger than xmin.")

    x = np.asarray(x_m, dtype=float)
    x_local = x - float(xmin)
    if np.any(x_local < -1.0e-12) or np.any(x_local > length + 1.0e-12):
        raise ValueError("x_m values must remain inside [xmin, xmax].")

    bottom_boundary = build_linear_substratum_values(
        x_m=np.asarray([float(xmin), float(xmax)], dtype=float),
        xmin=float(xmin),
        xmax=float(xmax),
        bottom_base_elevation_m=float(bottom_base_elevation_m),
        bottom_right_to_left_amplitude_m=float(bottom_right_to_left_amplitude_m),
    )
    west_bottom_m = float(bottom_boundary[0])
    west_thickness_m = float(west_head_m) - west_bottom_m
    if west_thickness_m <= 0.0:
        raise ValueError("west_head_m must remain above the local substratum.")

    west_discharge = solve_sloping_substratum_uniform_recharge_west_discharge_per_width(
        xmin=float(xmin),
        xmax=float(xmax),
        west_head_m=float(west_head_m),
        east_head_m=float(east_head_m),
        bottom_base_elevation_m=float(bottom_base_elevation_m),
        bottom_right_to_left_amplitude_m=float(bottom_right_to_left_amplitude_m),
        hydraulic_conductivity_m_per_s=float(hydraulic_conductivity_m_per_s),
        recharge_mm_day=float(recharge_mm_day),
    )
    length_grid, thickness_grid, success = _integrate_sloping_substratum_uniform_recharge_saturated_thickness(
        length_m=length,
        west_saturated_thickness_m=west_thickness_m,
        west_discharge_per_width_m2_s=float(west_discharge),
        hydraulic_conductivity_m_per_s=float(hydraulic_conductivity_m_per_s),
        bottom_slope_m_per_m=float(bottom_right_to_left_amplitude_m) / length,
        recharge_m_per_s=_mm_day_to_m_s(float(recharge_mm_day)),
        n_steps=4096,
    )
    if not success:
        raise RuntimeError(
            "Could not integrate the sloping-substratum recharge profile on the converged branch."
        )
    return np.interp(x_local, length_grid, thickness_grid)


def expected_sloping_substratum_uniform_recharge_profile_at_x(
    *,
    x_m: np.ndarray,
    xmin: float,
    xmax: float,
    west_head_m: float,
    east_head_m: float,
    bottom_base_elevation_m: float,
    bottom_right_to_left_amplitude_m: float,
    hydraulic_conductivity_m_per_s: float,
    recharge_mm_day: float,
) -> np.ndarray:
    """Return the steady head profile for one recharge hillslope."""
    bottom = build_linear_substratum_values(
        x_m=np.asarray(x_m, dtype=float),
        xmin=float(xmin),
        xmax=float(xmax),
        bottom_base_elevation_m=float(bottom_base_elevation_m),
        bottom_right_to_left_amplitude_m=float(bottom_right_to_left_amplitude_m),
    )
    thickness = expected_sloping_substratum_uniform_recharge_saturated_thickness_at_x(
        x_m=np.asarray(x_m, dtype=float),
        xmin=float(xmin),
        xmax=float(xmax),
        west_head_m=float(west_head_m),
        east_head_m=float(east_head_m),
        bottom_base_elevation_m=float(bottom_base_elevation_m),
        bottom_right_to_left_amplitude_m=float(bottom_right_to_left_amplitude_m),
        hydraulic_conductivity_m_per_s=float(hydraulic_conductivity_m_per_s),
        recharge_mm_day=float(recharge_mm_day),
    )
    return bottom + thickness


def expected_sloping_substratum_uniform_recharge_profile(
    *,
    xmin: float,
    xmax: float,
    ncol: int,
    west_head_m: float,
    east_head_m: float,
    bottom_base_elevation_m: float,
    bottom_right_to_left_amplitude_m: float,
    hydraulic_conductivity_m_per_s: float,
    recharge_mm_day: float,
) -> np.ndarray:
    """Return the steady recharge profile on one uniform cell-center support."""
    x = build_uniform_cell_center_x_values(
        xmin=float(xmin),
        xmax=float(xmax),
        ncol=int(ncol),
    )
    return expected_sloping_substratum_uniform_recharge_profile_at_x(
        x_m=x,
        xmin=float(xmin),
        xmax=float(xmax),
        west_head_m=float(west_head_m),
        east_head_m=float(east_head_m),
        bottom_base_elevation_m=float(bottom_base_elevation_m),
        bottom_right_to_left_amplitude_m=float(bottom_right_to_left_amplitude_m),
        hydraulic_conductivity_m_per_s=float(hydraulic_conductivity_m_per_s),
        recharge_mm_day=float(recharge_mm_day),
    )


__all__ = [
    "build_linear_substratum_values",
    "build_linear_topography_values",
    "build_validation_profile_x_values",
    "build_uniform_cell_center_x_values",
    "expected_sloping_substratum_constant_thickness_profile",
    "expected_sloping_substratum_constant_thickness_profile_at_x",
    "expected_sloping_substratum_fixed_head_profile",
    "expected_sloping_substratum_fixed_head_profile_at_x",
    "expected_sloping_substratum_fixed_head_saturated_thickness_at_x",
    "expected_sloping_substratum_uniform_recharge_profile",
    "expected_sloping_substratum_uniform_recharge_profile_at_x",
    "expected_sloping_substratum_uniform_recharge_saturated_thickness_at_x",
    "solve_sloping_substratum_fixed_head_discharge_per_width",
    "solve_sloping_substratum_uniform_recharge_west_discharge_per_width",
]
