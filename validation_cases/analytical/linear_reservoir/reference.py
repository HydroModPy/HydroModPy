"""Analytical reference of the linear reservoir, independent of the kernel.

The reference integrates the same one-state ODE with a fixed-step RK4 at a
thousandth of a day, an integration the backend never runs.
"""

from __future__ import annotations

import numpy as np

SECONDS_PER_DAY = 86400.0
STEPS_PER_DAY = 1000.0


def _rk4_step(state_m: float, rate_m_per_s: float, duration_s: float, tau_seconds: float) -> float:
    """One explicit RK4 step of ``ds/dt = rate - s / tau``."""

    def slope(state: float) -> float:
        return rate_m_per_s - state / tau_seconds

    k1 = slope(state_m)
    k2 = slope(state_m + 0.5 * duration_s * k1)
    k3 = slope(state_m + 0.5 * duration_s * k2)
    k4 = slope(state_m + duration_s * k3)
    return state_m + duration_s * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0


def run(
    rates_m_per_s: np.ndarray, durations_s: np.ndarray, state_m: float, tau_seconds: float
) -> np.ndarray:
    """The states one RK4 step of a thousandth of a day reaches per piece."""
    rates = np.asarray(rates_m_per_s, dtype=float)
    durations = np.asarray(durations_s, dtype=float)
    if rates.size != durations.size:
        raise ValueError(
            f"{rates.size} rates and {durations.size} durations: one duration per piece."
        )
    stored = np.empty(rates.size)
    depth = float(state_m)
    for i, (rate, duration) in enumerate(zip(rates, durations, strict=True)):
        steps = max(int(round(duration / (SECONDS_PER_DAY / STEPS_PER_DAY))), 1)
        step_s = float(duration) / steps
        for _ in range(steps):
            depth = _rk4_step(depth, rate, step_s, tau_seconds)
        stored[i] = depth
    return stored
