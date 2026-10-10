"""Hantush (1967) reference for the 2D recharge mound case.

A uniform recharge ``w`` falls on the rectangle ``|x| < l``, ``|y| < a`` of an
infinite unconfined aquifer of initial saturated thickness ``hi``. Linearized
with a mean saturated thickness ``b``, the head ``h`` above the aquifer base
grows as (Hantush 1967; Carleton 2010, USGS SIR 2010-5102)

    h**2 - hi**2 = (w / (2 K)) nu t [S*((l + x) n, (a + y) n) + S*((l + x) n, (a - y) n)
                                    + S*((l - x) n, (a + y) n) + S*((l - x) n, (a - y) n)],

    S*(alpha, beta) = int_0^1 erf(alpha / sqrt(tau)) erf(beta / sqrt(tau)) dtau,
    nu = K b / Sy,  n = 1 / sqrt(4 nu t).

Hantush takes ``b = (hi + hm(t)) / 2``, with ``hm`` the head at the centre of
the mound, which this module solves by fixed point at each time.
"""

from __future__ import annotations

import numpy as np
from scipy.integrate import quad_vec
from scipy.special import erf


def s_star(alpha, beta) -> np.ndarray:
    """Return Hantush's ``S*(alpha, beta)``, elementwise.

    The integral runs on ``u = sqrt(tau)``, where the front of
    ``erf(alpha / u)`` near ``u = |alpha|`` is resolved by the adaptive rule.
    """
    alpha_arr, beta_arr = np.broadcast_arrays(
        np.asarray(alpha, dtype=float), np.asarray(beta, dtype=float)
    )
    flat_alpha = alpha_arr.ravel()
    flat_beta = beta_arr.ravel()

    def integrand(u: float) -> np.ndarray:
        u = max(float(u), 1.0e-300)
        return 2.0 * u * erf(flat_alpha / u) * erf(flat_beta / u)

    value, _ = quad_vec(integrand, 0.0, 1.0, epsabs=1.0e-13, epsrel=1.0e-11, norm="max")
    return np.asarray(value, dtype=float).reshape(alpha_arr.shape)


def _corner_sum(x: np.ndarray, y: np.ndarray, *, n: float, half_x: float, half_y: float):
    return (
        s_star((half_x + x) * n, (half_y + y) * n)
        + s_star((half_x + x) * n, (half_y - y) * n)
        + s_star((half_x - x) * n, (half_y + y) * n)
        + s_star((half_x - x) * n, (half_y - y) * n)
    )


def _rise_with_thickness(
    x: np.ndarray,
    y: np.ndarray,
    *,
    time_seconds: float,
    mean_thickness_m: float,
    recharge_m_per_s: float,
    hydraulic_conductivity_m_per_s: float,
    specific_yield: float,
    initial_thickness_m: float,
    half_length_x_m: float,
    half_width_y_m: float,
) -> np.ndarray:
    nu = float(hydraulic_conductivity_m_per_s) * float(mean_thickness_m) / float(specific_yield)
    n = 1.0 / np.sqrt(4.0 * nu * float(time_seconds))
    total = _corner_sum(x, y, n=n, half_x=float(half_length_x_m), half_y=float(half_width_y_m))
    squared = (
        float(initial_thickness_m) ** 2
        + (float(recharge_m_per_s) / (2.0 * float(hydraulic_conductivity_m_per_s)))
        * nu
        * float(time_seconds)
        * total
    )
    return np.sqrt(squared) - float(initial_thickness_m)


def hantush_mean_thickness_m(
    *,
    time_seconds: float,
    recharge_m_per_s: float,
    hydraulic_conductivity_m_per_s: float,
    specific_yield: float,
    initial_thickness_m: float,
    half_length_x_m: float,
    half_width_y_m: float,
    max_iterations: int = 100,
) -> float:
    """Return Hantush's mean saturated thickness ``(hi + hm(t)) / 2`` at one time."""
    kwargs = dict(
        time_seconds=time_seconds,
        recharge_m_per_s=recharge_m_per_s,
        hydraulic_conductivity_m_per_s=hydraulic_conductivity_m_per_s,
        specific_yield=specific_yield,
        initial_thickness_m=initial_thickness_m,
        half_length_x_m=half_length_x_m,
        half_width_y_m=half_width_y_m,
    )
    centre = np.zeros(1, dtype=float)
    thickness = float(initial_thickness_m)
    for _ in range(int(max_iterations)):
        rise = float(_rise_with_thickness(centre, centre, mean_thickness_m=thickness, **kwargs)[0])
        updated = float(initial_thickness_m) + 0.5 * rise
        if abs(updated - thickness) <= 1.0e-12 * float(initial_thickness_m):
            return updated
        thickness = updated
    raise RuntimeError("Hantush mean thickness did not converge.")


def hantush_mound_rise(
    *,
    x,
    y,
    times_seconds,
    recharge_m_per_s: float,
    hydraulic_conductivity_m_per_s: float,
    specific_yield: float,
    initial_thickness_m: float,
    half_length_x_m: float,
    half_width_y_m: float,
) -> np.ndarray:
    """Return the head rise ``h - hi``, one row per time and one column per point.

    ``x`` and ``y`` are measured from the centre of the recharge rectangle,
    whose half sides are ``half_length_x_m`` along x and ``half_width_y_m``
    along y.
    """
    x_arr = np.asarray(x, dtype=float).reshape(-1)
    y_arr = np.asarray(y, dtype=float).reshape(-1)
    if x_arr.shape != y_arr.shape:
        raise ValueError("x and y must have the same length.")
    times = np.asarray(times_seconds, dtype=float).reshape(-1)
    if np.any(times <= 0.0):
        raise ValueError("times_seconds must be strictly positive.")
    common = dict(
        recharge_m_per_s=recharge_m_per_s,
        hydraulic_conductivity_m_per_s=hydraulic_conductivity_m_per_s,
        specific_yield=specific_yield,
        initial_thickness_m=initial_thickness_m,
        half_length_x_m=half_length_x_m,
        half_width_y_m=half_width_y_m,
    )
    rise = np.empty((times.size, x_arr.size), dtype=float)
    for index, time_seconds in enumerate(times):
        thickness = hantush_mean_thickness_m(time_seconds=float(time_seconds), **common)
        rise[index] = _rise_with_thickness(
            x_arr, y_arr, time_seconds=float(time_seconds), mean_thickness_m=thickness, **common
        )
    return rise


__all__ = ["hantush_mean_thickness_m", "hantush_mound_rise", "s_star"]
