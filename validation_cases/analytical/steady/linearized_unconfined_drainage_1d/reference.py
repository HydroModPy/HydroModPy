"""Analytical reference for the steady linearized unconfined drainage case."""

from __future__ import annotations

import numpy as np


def expected_linearized_unconfined_drainage_profile(
    *,
    x: np.ndarray,
    west_x: float,
    east_x: float,
    west_head_m: float,
    east_head_m: float,
    drainage_elevation_m: float,
    drainage_leakance_per_s: float,
    hydraulic_conductivity_m_per_s: float,
    reference_saturated_thickness_m: float,
) -> np.ndarray:
    """Return the steady linearized profile with distributed top drainage.

    The heads sit at ``west_x`` and ``east_x``, where the model holds them.
    ``drainage_leakance_per_s`` is the drain conductance per unit area, K / b
    when each drain takes ``C = K * cell_area / b``.
    """
    length = float(east_x) - float(west_x)
    if length <= 0.0:
        raise ValueError("east_x must be strictly larger than west_x.")
    transmissivity = float(hydraulic_conductivity_m_per_s) * float(reference_saturated_thickness_m)
    if transmissivity <= 0.0:
        raise ValueError(
            "hydraulic_conductivity_m_per_s * reference_saturated_thickness_m must be > 0."
        )

    drainage_rate_per_area = float(drainage_leakance_per_s)
    if drainage_rate_per_area < 0.0:
        raise ValueError("drainage_leakance_per_s must be >= 0.")

    x_local = np.asarray(x, dtype=float) - float(west_x)
    drainage_elevation = float(drainage_elevation_m)
    west_u = float(west_head_m) - drainage_elevation
    east_u = float(east_head_m) - drainage_elevation
    if west_u <= 0.0 or east_u <= 0.0:
        raise ValueError("Boundary heads must remain strictly above drainage_elevation_m.")

    if np.isclose(drainage_rate_per_area, 0.0):
        return float(west_head_m) + (float(east_head_m) - float(west_head_m)) * x_local / length

    lambda_value = np.sqrt(drainage_rate_per_area / transmissivity)
    denominator = np.sinh(lambda_value * length)
    west_shape = np.sinh(lambda_value * (length - x_local)) / denominator
    east_shape = np.sinh(lambda_value * x_local) / denominator
    return drainage_elevation + (west_u * west_shape) + (east_u * east_shape)
