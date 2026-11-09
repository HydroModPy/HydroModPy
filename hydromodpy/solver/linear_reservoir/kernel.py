"""Exact kernel of the linear reservoir backend, numpy only.

The state is the depth of water on the one cell of the run (m) and ``tau``
the time constant of the options. One piece of constant rate advances by the
closed form ``tau * r + (s - tau * r) * exp(-dur / tau)`` and gives back the
depth the piece releases at the outlet, closed on the mass by construction.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def advance_depth(
    depth_m: float, rate_m_per_s: float, duration_s: float, tau_seconds: float
) -> float:
    """Solve one piece of constant rate exactly, from *depth_m*."""
    if tau_seconds <= 0.0:
        raise ValueError(f"tau_seconds must be strictly positive, got {tau_seconds}.")
    r_tau = tau_seconds * rate_m_per_s
    return r_tau + (depth_m - r_tau) * np.exp(-duration_s / tau_seconds)


@dataclass(frozen=True, slots=True)
class Solved:
    """What one run of the kernel holds, in depth of water and in volume."""

    stored_m: np.ndarray
    """The state at the end of every piece, in depth of water on the cell."""

    released_m3: np.ndarray
    """The volume every piece sends to the outlet, in m3."""


def run(
    rates: np.ndarray,
    durations: np.ndarray,
    state_m: float,
    tau_seconds: float,
    area_m2: float,
) -> Solved:
    """Integrate every piece in order, from ``state_m``."""
    rates = np.asarray(rates, dtype=float)
    durations = np.asarray(durations, dtype=float)
    if rates.size != durations.size:
        raise ValueError(
            f"{rates.size} rates and {durations.size} durations: one duration per piece."
        )
    stored = np.empty(rates.size)
    released_m3 = np.empty(rates.size)
    depth = float(state_m)
    for i, (rate, duration) in enumerate(zip(rates, durations, strict=True)):
        after = advance_depth(depth, rate, duration, tau_seconds)
        stored[i] = after
        released_m3[i] = rate * duration * area_m2 - (after - depth) * area_m2
        depth = after
    return Solved(stored_m=stored, released_m3=released_m3)
