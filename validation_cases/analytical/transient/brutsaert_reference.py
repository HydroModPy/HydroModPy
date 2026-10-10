"""Analytical recession laws of a horizontal unconfined strip.

The strip has a no-flow divide on one side and a fixed-head outlet on the
other. ``B`` is the drainage length from the divide to the outlet and ``W``
the outlet width. Both laws solve the Boussinesq equation under the Dupuit
assumption, ``Sy dh/dt = K d/dx (h dh/dx)``.

- Nonlinear law. The outlet sits on the substratum (``h = 0``). Once the
  water table has the shape of the separable solution of Boussinesq (1904),
  the discharge obeys ``-dQ/dt = a Q^(3/2)``, that is
  ``Q(t) = (Q*^(-1/2) + a t / 2)^(-2)``. Brutsaert and Nieber (1977) write
  ``a = 4.804 K^(1/2) L / (f A^(3/2))`` for a channel of length ``L``
  drained from both banks, ``A = 2 B L``. The strip drains from one bank
  only, which halves the constant.
- Linear law. The outlet head stands ``D`` above the substratum and the head
  rise stays small against ``D``. After a steady uniform recharge stops, the
  discharge is a sum of exponential modes. Its late part is the single
  exponential of Brutsaert and Nieber (1977), ``-dQ/dt = a Q`` with
  ``a = pi^2 K D / (4 Sy B^2)``.
"""

from __future__ import annotations

import numpy as np
from scipy.special import beta as beta_function

SECONDS_PER_DAY = 86400.0

_SEPARABLE_SHAPE_INTEGRAL = float(beta_function(2.0 / 3.0, 0.5) / 3.0)

SEPARABLE_RECESSION_CONSTANT = 3.0 * _SEPARABLE_SHAPE_INTEGRAL**1.5
"""Constant ``C = 2.4025`` of the nonlinear law for a strip drained on one side.

``-dQ/dt = C K^(1/2) W Q^(3/2) / (Sy (B W)^(3/2))``. It is ``3 I^(3/2)`` with
``I`` the integral of ``p / sqrt(1 - p^3)`` from 0 to 1, the normalized
length of the separable water-table shape. Twice ``C`` is the 4.804 of
Brutsaert and Nieber (1977).
"""


def nonlinear_recession_coefficient(
    *,
    hydraulic_conductivity_m_per_s: float,
    specific_yield: float,
    drainage_length_m: float,
    outlet_width_m: float,
) -> float:
    """Return ``a`` of ``-dQ/dt = a Q^(3/2)`` for a strip drained on one side.

    The unit is ``m^(-3/2) s^(-1/2)``. ``Q^(-1/2)`` grows by ``a / 2`` per
    second once the separable water-table shape is reached.
    """
    area_m2 = float(drainage_length_m) * float(outlet_width_m)
    if area_m2 <= 0.0:
        raise ValueError("drainage_length_m and outlet_width_m must be positive.")
    return float(
        SEPARABLE_RECESSION_CONSTANT
        * np.sqrt(float(hydraulic_conductivity_m_per_s))
        * float(outlet_width_m)
        / (float(specific_yield) * area_m2**1.5)
    )


def nonlinear_recession_discharge(
    *,
    elapsed_seconds,
    recession_coefficient: float,
    virtual_origin: float,
) -> np.ndarray:
    """Return ``Q(t) = (y0 + a t / 2)^(-2)``.

    ``y0`` is ``Q^(-1/2)`` at ``t = 0`` on the late curve. It depends on the
    initial water table, which the late law does not describe.
    """
    elapsed = np.asarray(elapsed_seconds, dtype=float)
    return (float(virtual_origin) + 0.5 * float(recession_coefficient) * elapsed) ** -2


def linear_recession_rate(
    *,
    hydraulic_conductivity_m_per_s: float,
    specific_yield: float,
    saturated_thickness_m: float,
    drainage_length_m: float,
) -> float:
    """Return the decay rate ``a = pi^2 K D / (4 Sy B^2)`` of the first mode, in 1/s."""
    if float(drainage_length_m) <= 0.0:
        raise ValueError("drainage_length_m must be positive.")
    return float(
        np.pi**2
        * float(hydraulic_conductivity_m_per_s)
        * float(saturated_thickness_m)
        / (4.0 * float(specific_yield) * float(drainage_length_m) ** 2)
    )


def linear_recession_discharge(
    *,
    elapsed_seconds,
    initial_discharge_m3_s: float,
    recession_rate_per_s: float,
    drainage_length_m: float,
    recharged_length_m: float,
    n_modes: int = 2000,
) -> np.ndarray:
    """Return the linearized strip discharge after a steady uniform recharge stops.

    The recharge covers the strip from the divide over ``recharged_length_m``,
    which can stop short of the outlet: a model loses the recharge that falls
    on its fixed-head cells. With ``d = B - recharged_length_m`` and
    ``k = 2n - 1``,

    ``Q(t) = Q0 B / (B - d) * sum_n 8 cos(k pi d / (2B)) / (k pi)^2 exp(-k^2 a t)``.

    The weights sum to ``(B - d) / B``, so ``Q(0) = Q0``. The first mode alone
    is the late exponential law.
    """
    elapsed = np.asarray(elapsed_seconds, dtype=float)
    length = float(drainage_length_m)
    offset = length - float(recharged_length_m)
    if not 0.0 <= offset < length:
        raise ValueError("recharged_length_m must lie in (0, drainage_length_m].")
    k = 2.0 * np.arange(1, int(n_modes) + 1, dtype=float) - 1.0
    weights = 8.0 * np.cos(k * np.pi * offset / (2.0 * length)) / (k * np.pi) ** 2
    decay = np.exp(-np.outer(elapsed, k**2) * float(recession_rate_per_s))
    scale = float(initial_discharge_m3_s) * length / (length - offset)
    return scale * (decay @ weights)


def linear_recession_period_mean_discharge(
    *,
    period_start_seconds,
    period_end_seconds,
    initial_discharge_m3_s: float,
    recession_rate_per_s: float,
    drainage_length_m: float,
    recharged_length_m: float,
    n_modes: int = 2000,
) -> np.ndarray:
    """Return the mean of :func:`linear_recession_discharge` over each period.

    A run stores the mean flux of each stress period, so the reference is the
    integral of each mode over the period ``[t0, t1)`` divided by its length:
    ``exp(-k^2 a t0) (1 - exp(-k^2 a (t1 - t0))) / (k^2 a (t1 - t0))``.
    """
    start = np.asarray(period_start_seconds, dtype=float).reshape(-1)
    length_s = np.asarray(period_end_seconds, dtype=float).reshape(-1) - start
    if np.any(length_s <= 0.0) or np.any(start < 0.0):
        raise ValueError("periods must start at or after 0 and have a positive length.")
    length = float(drainage_length_m)
    offset = length - float(recharged_length_m)
    if not 0.0 <= offset < length:
        raise ValueError("recharged_length_m must lie in (0, drainage_length_m].")
    k = 2.0 * np.arange(1, int(n_modes) + 1, dtype=float) - 1.0
    weights = 8.0 * np.cos(k * np.pi * offset / (2.0 * length)) / (k * np.pi) ** 2
    rate = k**2 * float(recession_rate_per_s)
    span = np.outer(length_s, rate)
    mean_decay = np.exp(-np.outer(start, rate)) * (-np.expm1(-span) / span)
    scale = float(initial_discharge_m3_s) * length / (length - offset)
    return scale * (mean_decay @ weights)


def nonlinear_recession_period_mean_discharge(
    *,
    period_start_seconds,
    period_end_seconds,
    recession_coefficient: float,
    virtual_origin: float,
) -> np.ndarray:
    """Return the mean of :func:`nonlinear_recession_discharge` over each period.

    With ``y(t) = y0 + a t / 2`` and ``Q = y^(-2)``, the integral of ``Q`` over
    ``[t0, t1)`` is ``2 (1 / y(t0) - 1 / y(t1)) / a``, so the mean is
    ``1 / (y(t0) y(t1))``.
    """
    start = np.asarray(period_start_seconds, dtype=float).reshape(-1)
    end = np.asarray(period_end_seconds, dtype=float).reshape(-1)
    half = 0.5 * float(recession_coefficient)
    return 1.0 / ((float(virtual_origin) + half * start) * (float(virtual_origin) + half * end))


def nonlinear_virtual_origin_from_period_means(
    *,
    period_start_seconds,
    period_length_seconds: float,
    mean_discharge_m3_s,
    recession_coefficient: float,
) -> float:
    """Return ``y0`` of the nonlinear law from discharges averaged over periods.

    Inverts :func:`nonlinear_recession_period_mean_discharge`: a mean ``Qm``
    over ``[t0, t0 + dt)`` gives ``y(t0) (y(t0) + a dt / 2) = 1 / Qm``. The
    estimate is the mean of ``y(t0) - a t0 / 2`` over the periods given.
    """
    start = np.asarray(period_start_seconds, dtype=float).reshape(-1)
    mean_q = np.asarray(mean_discharge_m3_s, dtype=float).reshape(-1)
    half = 0.5 * float(recession_coefficient)
    step = half * float(period_length_seconds)
    y_start = 0.5 * (-step + np.sqrt(step**2 + 4.0 / mean_q))
    return float(np.mean(y_start - half * start))


__all__ = [
    "SECONDS_PER_DAY",
    "SEPARABLE_RECESSION_CONSTANT",
    "linear_recession_discharge",
    "linear_recession_period_mean_discharge",
    "linear_recession_rate",
    "nonlinear_recession_coefficient",
    "nonlinear_recession_discharge",
    "nonlinear_recession_period_mean_discharge",
    "nonlinear_virtual_origin_from_period_means",
]
