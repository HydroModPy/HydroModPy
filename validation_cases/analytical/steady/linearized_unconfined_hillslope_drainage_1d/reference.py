"""Analytical reference for the steady hillslope-drainage linearized case."""

from __future__ import annotations

import numpy as np


def build_linear_topography_values(
    *,
    x_m: np.ndarray,
    xmin: float,
    xmax: float,
    topography_base_elevation_m: float,
    topography_right_to_left_amplitude_m: float,
) -> np.ndarray:
    """Return linear topography values sampled at explicit x positions.

    The surface is ``base + amplitude`` at ``xmin`` and ``base`` at ``xmax``.
    """
    length = float(xmax) - float(xmin)
    if length <= 0.0:
        raise ValueError("xmax must be strictly larger than xmin.")

    x = np.asarray(x_m, dtype=float)
    x_local = x - float(xmin)
    return float(topography_base_elevation_m) + float(topography_right_to_left_amplitude_m) * (
        1.0 - (x_local / length)
    )


def expected_linearized_unconfined_hillslope_drainage_profile_at_x(
    *,
    x_m: np.ndarray,
    surface_west_x: float,
    surface_east_x: float,
    west_x: float,
    east_x: float,
    west_head_m: float,
    east_head_m: float,
    drainage_conductance_m2_per_s: float,
    cell_area_m2: float,
    hydraulic_conductivity_m_per_s: float,
    reference_saturated_thickness_m: float,
    topography_base_elevation_m: float,
    topography_right_to_left_amplitude_m: float,
) -> np.ndarray:
    """Return the steady linearized profile sampled at explicit x positions.

    The drains sit on the linear topography, which takes its west and east
    values at ``surface_west_x`` and ``surface_east_x``. The heads sit at
    ``west_x`` and ``east_x``, where the model holds them. A linear drain
    elevation leaves ``u = h - z_d`` the solution of ``T u'' = (C / A) u``.
    """
    length = float(east_x) - float(west_x)
    if length <= 0.0:
        raise ValueError("east_x must be strictly larger than west_x.")
    if float(cell_area_m2) <= 0.0:
        raise ValueError("cell_area_m2 must be > 0.")

    transmissivity = float(hydraulic_conductivity_m_per_s) * float(reference_saturated_thickness_m)
    if transmissivity <= 0.0:
        raise ValueError(
            "hydraulic_conductivity_m_per_s * reference_saturated_thickness_m must be > 0."
        )

    drainage_rate_per_area = float(drainage_conductance_m2_per_s) / float(cell_area_m2)
    if drainage_rate_per_area < 0.0:
        raise ValueError("drainage_conductance_m2_per_s must be >= 0.")

    def topography(points: np.ndarray) -> np.ndarray:
        return build_linear_topography_values(
            x_m=points,
            xmin=float(surface_west_x),
            xmax=float(surface_east_x),
            topography_base_elevation_m=float(topography_base_elevation_m),
            topography_right_to_left_amplitude_m=float(topography_right_to_left_amplitude_m),
        )

    x = np.asarray(x_m, dtype=float)
    x_local = x - float(west_x)
    west_u = float(west_head_m) - float(topography(np.asarray([float(west_x)]))[0])
    east_u = float(east_head_m) - float(topography(np.asarray([float(east_x)]))[0])
    if west_u <= 0.0 or east_u <= 0.0:
        raise ValueError("Boundary heads must remain strictly above the local topography.")

    if np.isclose(drainage_rate_per_area, 0.0):
        return float(west_head_m) + (float(east_head_m) - float(west_head_m)) * x_local / length

    lambda_value = np.sqrt(drainage_rate_per_area / transmissivity)
    denominator = np.sinh(lambda_value * length)
    west_shape = np.sinh(lambda_value * (length - x_local)) / denominator
    east_shape = np.sinh(lambda_value * x_local) / denominator
    return topography(x) + (west_u * west_shape) + (east_u * east_shape)
