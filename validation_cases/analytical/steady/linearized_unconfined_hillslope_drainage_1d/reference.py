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
    """Return linear topography values sampled at explicit x positions."""
    length = float(xmax) - float(xmin)
    if length <= 0.0:
        raise ValueError("xmax must be strictly larger than xmin.")

    x = np.asarray(x_m, dtype=float)
    x_local = x - float(xmin)
    return float(topography_base_elevation_m) + float(topography_right_to_left_amplitude_m) * (
        1.0 - (x_local / length)
    )


def build_linear_topography_profile(
    *,
    xmin: float,
    xmax: float,
    ncol: int,
    topography_base_elevation_m: float,
    topography_right_to_left_amplitude_m: float,
) -> np.ndarray:
    """Return one linear topographic profile on a uniform support."""
    if int(ncol) <= 0:
        raise ValueError("ncol must be > 0.")
    x = np.linspace(float(xmin), float(xmax), int(ncol), dtype=float)
    return build_linear_topography_values(
        x_m=x,
        xmin=float(xmin),
        xmax=float(xmax),
        topography_base_elevation_m=float(topography_base_elevation_m),
        topography_right_to_left_amplitude_m=float(topography_right_to_left_amplitude_m),
    )


def expected_linearized_unconfined_hillslope_drainage_profile_at_x(
    *,
    x_m: np.ndarray,
    xmin: float,
    xmax: float,
    west_head_m: float,
    east_head_m: float,
    drainage_conductance_m2_per_s: float,
    cell_area_m2: float,
    hydraulic_conductivity_m_per_s: float,
    reference_saturated_thickness_m: float,
    topography_base_elevation_m: float,
    topography_right_to_left_amplitude_m: float,
) -> np.ndarray:
    """Return the steady linearized profile sampled at explicit x positions."""
    length = float(xmax) - float(xmin)
    if length <= 0.0:
        raise ValueError("xmax must be strictly larger than xmin.")
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

    x = np.asarray(x_m, dtype=float)
    x_local = x - float(xmin)
    topography_profile = build_linear_topography_values(
        x_m=x,
        xmin=float(xmin),
        xmax=float(xmax),
        topography_base_elevation_m=float(topography_base_elevation_m),
        topography_right_to_left_amplitude_m=float(topography_right_to_left_amplitude_m),
    )
    west_u = float(west_head_m) - float(topography_profile[0])
    east_u = float(east_head_m) - float(topography_profile[-1])
    if west_u <= 0.0 or east_u <= 0.0:
        raise ValueError("Boundary heads must remain strictly above the local topography.")

    if np.isclose(drainage_rate_per_area, 0.0):
        return np.linspace(float(west_head_m), float(east_head_m), int(ncol), dtype=float)

    lambda_value = np.sqrt(drainage_rate_per_area / transmissivity)
    denominator = np.sinh(lambda_value * length)
    west_shape = np.sinh(lambda_value * (length - x_local)) / denominator
    east_shape = np.sinh(lambda_value * x_local) / denominator
    return topography_profile + (west_u * west_shape) + (east_u * east_shape)


def expected_linearized_unconfined_hillslope_drainage_profile(
    *,
    xmin: float,
    xmax: float,
    ncol: int,
    west_head_m: float,
    east_head_m: float,
    drainage_conductance_m2_per_s: float,
    cell_area_m2: float,
    hydraulic_conductivity_m_per_s: float,
    reference_saturated_thickness_m: float,
    topography_base_elevation_m: float,
    topography_right_to_left_amplitude_m: float,
) -> np.ndarray:
    """Return the steady linearized profile with linearly varying drainage elevation."""
    if int(ncol) <= 0:
        raise ValueError("ncol must be > 0.")
    x = np.linspace(float(xmin), float(xmax), int(ncol), dtype=float)
    return expected_linearized_unconfined_hillslope_drainage_profile_at_x(
        x_m=x,
        xmin=float(xmin),
        xmax=float(xmax),
        west_head_m=float(west_head_m),
        east_head_m=float(east_head_m),
        drainage_conductance_m2_per_s=float(drainage_conductance_m2_per_s),
        cell_area_m2=float(cell_area_m2),
        hydraulic_conductivity_m_per_s=float(hydraulic_conductivity_m_per_s),
        reference_saturated_thickness_m=float(reference_saturated_thickness_m),
        topography_base_elevation_m=float(topography_base_elevation_m),
        topography_right_to_left_amplitude_m=float(topography_right_to_left_amplitude_m),
    )
