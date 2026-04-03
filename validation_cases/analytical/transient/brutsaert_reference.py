"""Analytical Brutsaert recession helpers shared by validation cases."""

from __future__ import annotations

import numpy as np


SECONDS_PER_DAY = 86400.0


def _resolve_area_length(
    *,
    area_m2: float | None,
    channel_length_m: float | None,
) -> tuple[float, float]:
    """Resolve one consistent watershed area/channel-length pair."""
    if area_m2 is None and channel_length_m is None:
        raise ValueError("Either area_m2 or channel_length_m must be provided.")
    if channel_length_m is None:
        channel_length_m = 1.4 * np.sqrt(float(area_m2))
    if area_m2 is None:
        area_m2 = (float(channel_length_m) / 1.4) ** 2
    return float(area_m2), float(channel_length_m)


def compute_characteristic_time(
    *,
    initial_discharge_m3_s: float,
    hydraulic_conductivity_m_per_s: float,
    specific_yield: float,
    solution: str,
    aquifer_thickness_m: float | None = None,
    area_m2: float | None = None,
    channel_length_m: float | None = None,
    active_drainage_fraction: float = 0.7,
    linearization_constant: float = 0.346,
) -> float:
    """Return the Brutsaert characteristic time in seconds."""
    area_m2, channel_length_m = _resolve_area_length(
        area_m2=area_m2,
        channel_length_m=channel_length_m,
    )
    normalized_solution = str(solution).strip().lower()
    conductivity = float(hydraulic_conductivity_m_per_s)
    storage = float(specific_yield)
    active_area_m2 = float(active_drainage_fraction) * float(area_m2)
    if active_area_m2 <= 0.0:
        raise ValueError("active_drainage_fraction * area_m2 must remain positive.")

    if normalized_solution == "exponential":
        if aquifer_thickness_m is None:
            raise ValueError("aquifer_thickness_m is required for the exponential solution.")
        recession_rate_per_s = (
            (np.pi**2)
            * conductivity
            * float(linearization_constant)
            * float(aquifer_thickness_m)
            * (channel_length_m**2)
            / (storage * (active_area_m2**2))
        )
        return float(1.0 / recession_rate_per_s)

    if normalized_solution == "boussinesq":
        beta = (
            (4.8038 / 2.0)
            * np.sqrt(conductivity)
            * channel_length_m
            / (storage * (active_area_m2**1.5))
        )
        return float(1.0 / (beta * np.sqrt(float(initial_discharge_m3_s))))

    raise ValueError(f"Unsupported Brutsaert solution '{solution}'.")


def simulate_baseflow(
    *,
    elapsed_seconds,
    initial_discharge_m3_s: float,
    hydraulic_conductivity_m_per_s: float,
    specific_yield: float,
    solution: str,
    aquifer_thickness_m: float | None = None,
    area_m2: float | None = None,
    channel_length_m: float | None = None,
    active_drainage_fraction: float = 0.7,
    linearization_constant: float = 0.346,
) -> np.ndarray:
    """Return the Brutsaert discharge series evaluated at one time grid."""
    area_m2, channel_length_m = _resolve_area_length(
        area_m2=area_m2,
        channel_length_m=channel_length_m,
    )
    normalized_solution = str(solution).strip().lower()
    elapsed = np.asarray(elapsed_seconds, dtype=float)
    conductivity = float(hydraulic_conductivity_m_per_s)
    storage = float(specific_yield)
    active_area_m2 = float(active_drainage_fraction) * float(area_m2)
    initial_discharge = float(initial_discharge_m3_s)
    if active_area_m2 <= 0.0:
        raise ValueError("active_drainage_fraction * area_m2 must remain positive.")

    if normalized_solution == "exponential":
        if aquifer_thickness_m is None:
            raise ValueError("aquifer_thickness_m is required for the exponential solution.")
        recession_rate_per_s = (
            (np.pi**2)
            * conductivity
            * float(linearization_constant)
            * float(aquifer_thickness_m)
            * (channel_length_m**2)
            / (storage * (active_area_m2**2))
        )
        return initial_discharge * np.exp(-recession_rate_per_s * elapsed)

    if normalized_solution == "boussinesq":
        beta = (
            (4.8038 / 2.0)
            * np.sqrt(conductivity)
            * channel_length_m
            / (storage * (active_area_m2**1.5))
        )
        return (initial_discharge ** (-0.5) + (beta * elapsed)) ** (-2)

    raise ValueError(f"Unsupported Brutsaert solution '{solution}'.")


__all__ = [
    "SECONDS_PER_DAY",
    "compute_characteristic_time",
    "simulate_baseflow",
]
