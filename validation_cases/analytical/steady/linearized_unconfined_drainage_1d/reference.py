"""Analytical reference for the steady linearized unconfined drainage case."""

from __future__ import annotations

import numpy as np


def expected_linearized_unconfined_drainage_profile(
    *,
    xmin: float,
    xmax: float,
    ncol: int,
    west_head_m: float,
    east_head_m: float,
    drainage_elevation_m: float,
    drainage_conductance_m2_per_s: float,
    cell_area_m2: float,
    hydraulic_conductivity_m_per_s: float,
    reference_saturated_thickness_m: float,
) -> np.ndarray:
    """Return the steady linearized profile with distributed top drainage."""
    length = float(xmax) - float(xmin)
    if length <= 0.0:
        raise ValueError("xmax must be strictly larger than xmin.")
    if int(ncol) <= 0:
        raise ValueError("ncol must be > 0.")
    if float(cell_area_m2) <= 0.0:
        raise ValueError("cell_area_m2 must be > 0.")

    transmissivity = (
        float(hydraulic_conductivity_m_per_s)
        * float(reference_saturated_thickness_m)
    )
    if transmissivity <= 0.0:
        raise ValueError("hydraulic_conductivity_m_per_s * reference_saturated_thickness_m must be > 0.")

    drainage_rate_per_area = float(drainage_conductance_m2_per_s) / float(cell_area_m2)
    if drainage_rate_per_area < 0.0:
        raise ValueError("drainage_conductance_m2_per_s must be >= 0.")

    x_local = np.linspace(0.0, length, int(ncol), dtype=float)
    drainage_elevation = float(drainage_elevation_m)
    west_u = float(west_head_m) - drainage_elevation
    east_u = float(east_head_m) - drainage_elevation
    if west_u <= 0.0 or east_u <= 0.0:
        raise ValueError("Boundary heads must remain strictly above drainage_elevation_m.")

    if np.isclose(drainage_rate_per_area, 0.0):
        return np.linspace(float(west_head_m), float(east_head_m), int(ncol), dtype=float)

    lambda_value = np.sqrt(drainage_rate_per_area / transmissivity)
    denominator = np.sinh(lambda_value * length)
    west_shape = np.sinh(lambda_value * (length - x_local)) / denominator
    east_shape = np.sinh(lambda_value * x_local) / denominator
    return drainage_elevation + (west_u * west_shape) + (east_u * east_shape)
