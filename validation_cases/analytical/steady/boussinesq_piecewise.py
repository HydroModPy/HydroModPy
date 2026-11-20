"""Closed-form helpers for steady unconfined Boussinesq cases with piecewise K."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

SECONDS_PER_DAY = 86400.0
MM_PER_M = 1000.0


def mm_day_to_m_s(value: float) -> float:
    """Convert a recharge rate from mm/day to m/s."""
    return float(value) / MM_PER_M / SECONDS_PER_DAY


def validate_piecewise_constant_segments(
    *,
    start: float,
    end: float,
    breaks,
    values,
    coordinate_label: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Validate one ordered piecewise-constant support and return edges/values."""
    start_value = float(start)
    end_value = float(end)
    if end_value <= start_value:
        raise ValueError(f"{coordinate_label} end must be strictly larger than start.")

    break_values = np.asarray(tuple(breaks), dtype=float)
    conductivity_values = np.asarray(tuple(values), dtype=float)
    if conductivity_values.ndim != 1:
        raise ValueError("values must define one flat sequence of conductivities.")
    if conductivity_values.size != break_values.size + 1:
        raise ValueError("Piecewise conductivities must have len(breaks) + 1 values.")
    if np.any(conductivity_values <= 0.0):
        raise ValueError("Piecewise conductivities must stay strictly positive.")
    if break_values.size and (
        np.any(np.diff(break_values) <= 0.0)
        or np.any(break_values <= start_value)
        or np.any(break_values >= end_value)
    ):
        raise ValueError(
            f"Piecewise {coordinate_label} breaks must be strictly increasing inside "
            f"({start_value}, {end_value})."
        )

    edges = np.concatenate(([start_value], break_values, [end_value])).astype(float)
    return edges, conductivity_values.astype(float)


def integrate_piecewise_inverse(points, *, edges: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Return ``∫ ds / K(s)`` from the first edge to each requested point."""
    point_values = np.asarray(points, dtype=float)
    out = np.zeros_like(point_values, dtype=float)
    for left_edge, right_edge, conductivity in zip(
        edges[:-1],
        edges[1:],
        values,
        strict=False,
    ):
        capped = np.clip(point_values, left_edge, right_edge)
        out += (capped - left_edge) / float(conductivity)
    return out


def integrate_piecewise_linear_weight(
    points, *, edges: np.ndarray, values: np.ndarray
) -> np.ndarray:
    """Return ``∫ s ds / K(s)`` from the first edge to each requested point."""
    point_values = np.asarray(points, dtype=float)
    out = np.zeros_like(point_values, dtype=float)
    for left_edge, right_edge, conductivity in zip(
        edges[:-1],
        edges[1:],
        values,
        strict=False,
    ):
        capped = np.clip(point_values, left_edge, right_edge)
        out += ((capped**2) - left_edge**2) / (2.0 * float(conductivity))
    return out


def _head_from_squared(head_squared) -> np.ndarray:
    head_squared_arr = np.asarray(head_squared, dtype=float)
    if np.any(head_squared_arr < 0.0):
        raise ValueError("Analytical head-squared profile became negative.")
    return np.sqrt(head_squared_arr)


def _local_piecewise_support(
    *,
    x,
    start_x: float,
    end_x: float,
    x_zone_breaks_m: Iterable[float],
    hydraulic_conductivity_m_per_s_by_zone: Iterable[float],
) -> tuple[np.ndarray, float, np.ndarray, np.ndarray]:
    """Return local abscissas, length, zone edges and zone K on ``[start_x, end_x]``.

    The zone breaks are absolute positions, the faces where the model changes
    K. Breaks outside ``(start_x, end_x)`` cannot be posed and are rejected.
    """
    length = float(end_x) - float(start_x)
    x_local = np.asarray(x, dtype=float) - float(start_x)
    breaks_local = np.asarray(tuple(x_zone_breaks_m), dtype=float) - float(start_x)
    edges, conductivity = validate_piecewise_constant_segments(
        start=0.0,
        end=length,
        breaks=breaks_local,
        values=hydraulic_conductivity_m_per_s_by_zone,
        coordinate_label="x",
    )
    return x_local, length, edges, conductivity


def expected_boussinesq_fixed_head_piecewise_profile(
    *,
    x,
    west_x: float,
    east_x: float,
    west_head: float,
    east_head: float,
    x_zone_breaks_m: Iterable[float],
    hydraulic_conductivity_m_per_s_by_zone: Iterable[float],
) -> np.ndarray:
    """Return the steady 1D Boussinesq profile with piecewise-constant K and no recharge.

    The heads sit at ``west_x`` and ``east_x``, where the model holds them.
    """
    x_local, length, edges, conductivity = _local_piecewise_support(
        x=x,
        start_x=west_x,
        end_x=east_x,
        x_zone_breaks_m=x_zone_breaks_m,
        hydraulic_conductivity_m_per_s_by_zone=hydraulic_conductivity_m_per_s_by_zone,
    )
    resistance = integrate_piecewise_inverse(x_local, edges=edges, values=conductivity)
    total_resistance = float(
        integrate_piecewise_inverse(
            np.asarray([length], dtype=float), edges=edges, values=conductivity
        )[0]
    )
    head_squared = float(west_head) ** 2 + (
        (float(east_head) ** 2 - float(west_head) ** 2) * (resistance / total_resistance)
    )
    return _head_from_squared(head_squared)


def expected_boussinesq_uniform_recharge_piecewise_profile(
    *,
    x,
    west_x: float,
    east_x: float,
    west_head: float,
    east_head: float,
    recharge_mm_day: float,
    x_zone_breaks_m: Iterable[float],
    hydraulic_conductivity_m_per_s_by_zone: Iterable[float],
) -> np.ndarray:
    """Return the steady 1D Boussinesq profile with recharge and piecewise-constant K.

    The heads sit at ``west_x`` and ``east_x``, where the model holds them.
    """
    recharge_m_per_s = mm_day_to_m_s(recharge_mm_day)
    x_local, length, edges, conductivity = _local_piecewise_support(
        x=x,
        start_x=west_x,
        end_x=east_x,
        x_zone_breaks_m=x_zone_breaks_m,
        hydraulic_conductivity_m_per_s_by_zone=hydraulic_conductivity_m_per_s_by_zone,
    )
    resistance = integrate_piecewise_inverse(x_local, edges=edges, values=conductivity)
    weighted_integral = integrate_piecewise_linear_weight(x_local, edges=edges, values=conductivity)
    total_resistance = float(
        integrate_piecewise_inverse(
            np.asarray([length], dtype=float), edges=edges, values=conductivity
        )[0]
    )
    total_weighted = float(
        integrate_piecewise_linear_weight(
            np.asarray([length], dtype=float), edges=edges, values=conductivity
        )[0]
    )
    west_head_sq = float(west_head) ** 2
    east_head_sq = float(east_head) ** 2
    integration_constant = (
        east_head_sq - west_head_sq + 2.0 * recharge_m_per_s * total_weighted
    ) / total_resistance
    head_squared = (
        west_head_sq
        + integration_constant * resistance
        - 2.0 * recharge_m_per_s * weighted_integral
    )
    return _head_from_squared(head_squared)


def expected_boussinesq_divide_fixed_head_piecewise_profile(
    *,
    x,
    divide_x: float,
    east_x: float,
    east_head: float,
    recharge_mm_day: float,
    x_zone_breaks_m: Iterable[float],
    hydraulic_conductivity_m_per_s_by_zone: Iterable[float],
) -> np.ndarray:
    """Return the steady 1D Boussinesq profile with a west divide, an east head and piecewise K.

    The no-flow divide sits at ``divide_x`` (the west face) and the head at
    ``east_x``, where the model holds it.
    """
    recharge_m_per_s = mm_day_to_m_s(recharge_mm_day)
    x_local, length, edges, conductivity = _local_piecewise_support(
        x=x,
        start_x=divide_x,
        end_x=east_x,
        x_zone_breaks_m=x_zone_breaks_m,
        hydraulic_conductivity_m_per_s_by_zone=hydraulic_conductivity_m_per_s_by_zone,
    )
    weighted_integral = integrate_piecewise_linear_weight(x_local, edges=edges, values=conductivity)
    total_weighted = float(
        integrate_piecewise_linear_weight(
            np.asarray([length], dtype=float), edges=edges, values=conductivity
        )[0]
    )
    head_squared = float(east_head) ** 2 + 2.0 * recharge_m_per_s * (
        total_weighted - weighted_integral
    )
    return _head_from_squared(head_squared)


def expected_boussinesq_circular_island_piecewise_k_head(
    *,
    radius_m,
    island_radius_m: float,
    recharge_mm_day: float,
    ring_radius_breaks_m: Iterable[float],
    hydraulic_conductivity_m_per_s_by_ring: Iterable[float],
    substratum_elevation_m: float,
    sea_level_m: float = 0.0,
) -> np.ndarray:
    """Return the steady radial Boussinesq head for concentric piecewise-constant K rings."""
    radius = np.asarray(radius_m, dtype=float)
    shoreline_radius = float(island_radius_m)
    recharge_m_per_s = mm_day_to_m_s(recharge_mm_day)
    substratum = float(substratum_elevation_m)
    sea_level = float(sea_level_m)

    if shoreline_radius <= 0.0:
        raise ValueError("island_radius_m must be > 0.")
    if substratum >= sea_level:
        raise ValueError("substratum_elevation_m must stay below sea_level_m.")

    edges, conductivity = validate_piecewise_constant_segments(
        start=0.0,
        end=shoreline_radius,
        breaks=ring_radius_breaks_m,
        values=hydraulic_conductivity_m_per_s_by_ring,
        coordinate_label="radius",
    )
    total_weighted = float(
        integrate_piecewise_linear_weight(
            np.asarray([shoreline_radius], dtype=float),
            edges=edges,
            values=conductivity,
        )[0]
    )

    head = np.full(radius.shape, sea_level, dtype=float)
    land_mask = radius <= shoreline_radius
    if np.any(land_mask):
        weighted_integral = integrate_piecewise_linear_weight(
            radius[land_mask],
            edges=edges,
            values=conductivity,
        )
        coastal_thickness = sea_level - substratum
        thickness_squared = coastal_thickness**2 + recharge_m_per_s * (
            total_weighted - weighted_integral
        )
        head[land_mask] = substratum + _head_from_squared(thickness_squared)
    return head
