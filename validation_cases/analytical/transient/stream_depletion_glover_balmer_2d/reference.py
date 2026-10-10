"""Closed form of a well pumping beside a straight stream held at a fixed head.

The stream is a fully penetrating straight line held at the initial head, the
aquifer homogeneous and semi-infinite on the side of the well. The method of
images replaces the stream by a recharge well of the same rate mirrored across
it (Theis 1941). The drawdown is then the Theis drawdown of the well minus that
of its image, and the share of the pumping rate drawn from the stream is
``erfc(sqrt(S a^2 / (4 T t)))`` (Glover and Balmer 1954), where ``a`` is the
distance from the well to the stream.
"""

from __future__ import annotations

import math

import numpy as np

SECONDS_PER_DAY = 86400.0


def transmissivity_m2_day(
    *, hydraulic_conductivity_m_per_s: float, saturated_thickness_m: float
) -> float:
    """Return ``T = K b`` in m2/day."""
    return float(hydraulic_conductivity_m_per_s) * SECONDS_PER_DAY * float(saturated_thickness_m)


def image_well_drawdown(
    *,
    x_m,
    y_m,
    times_days,
    well_xy: tuple[float, float],
    stream_x_m: float,
    pumping_rate_m3_day: float,
    transmissivity_m2_day: float,
    storage: float,
) -> np.ndarray:
    """Return the drawdown, one row per time and one column per point.

    ``s = Q / (4 pi T) [E1(r1^2 S / (4 T t)) - E1(r2^2 S / (4 T t))]``, with
    ``r1`` the distance to the well and ``r2`` the distance to its image across
    the stream line ``x = stream_x_m``. The well point itself is singular and
    must not be passed.
    """
    from scipy.special import exp1

    x = np.asarray(x_m, dtype=float).reshape(-1)
    y = np.asarray(y_m, dtype=float).reshape(-1)
    t = np.asarray(times_days, dtype=float).reshape(-1)
    if x.shape != y.shape:
        raise ValueError("x_m and y_m must have the same length.")
    if np.any(t <= 0.0):
        raise ValueError("times_days must be strictly positive.")
    well_x, well_y = float(well_xy[0]), float(well_xy[1])
    image_x = 2.0 * float(stream_x_m) - well_x
    r1_sq = (x - well_x) ** 2 + (y - well_y) ** 2
    r2_sq = (x - image_x) ** 2 + (y - well_y) ** 2
    if np.any(r1_sq <= 0.0):
        raise ValueError("The drawdown is singular at the well.")
    scale = float(storage) / (4.0 * float(transmissivity_m2_day) * t[:, None])
    well_function = exp1(r1_sq[None, :] * scale) - exp1(r2_sq[None, :] * scale)
    return float(pumping_rate_m3_day) * well_function / (4.0 * math.pi * transmissivity_m2_day)


def stream_depletion_fraction(
    *,
    times_days,
    distance_m: float,
    transmissivity_m2_day: float,
    storage: float,
) -> np.ndarray:
    """Return ``Qs / Q = erfc(sqrt(S a^2 / (4 T t)))`` at each time."""
    from scipy.special import erfc

    t = np.asarray(times_days, dtype=float).reshape(-1)
    if np.any(t <= 0.0):
        raise ValueError("times_days must be strictly positive.")
    if float(distance_m) <= 0.0:
        raise ValueError("distance_m must be strictly positive.")
    argument = np.sqrt(
        float(storage) * float(distance_m) ** 2 / (4.0 * float(transmissivity_m2_day) * t)
    )
    return np.asarray(erfc(argument), dtype=float)


__all__ = [
    "SECONDS_PER_DAY",
    "image_well_drawdown",
    "stream_depletion_fraction",
    "transmissivity_m2_day",
]
