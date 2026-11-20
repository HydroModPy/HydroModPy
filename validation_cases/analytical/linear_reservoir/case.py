"""State and volume the linear reservoir holds, read backward from the store.

The case runs the backend on a synthetic basin of one cell: one storm of
5 days at 5 mm/day, then 20 dry days, with a time constant of 30 days. It
records the relative gap of the states and of the released volumes against
the reference, at the tolerance the case file declares.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from validation_cases.analytical.linear_reservoir.reference import run as reference_run

CASE_DIR_TOLERANCE = "1e-4"


def rain_of(days: int, storm_days: int, rate_m_per_s: float) -> np.ndarray:
    """The daily rates of the case: one storm, then dry days."""
    rain = np.zeros(days)
    rain[:storm_days] = rate_m_per_s
    return rain


def compute_linear_reservoir_reference(
    rates_m_per_s: np.ndarray,
    durations_s: np.ndarray,
    tau_seconds: float,
) -> tuple[np.ndarray, np.ndarray]:
    """The state and the released volume the RK4 reference holds, one piece.

    The reference integrates the same ODE with a fixed-step RK4 (the code of
    :func:`reference.run`), an integration the backend never runs. The
    depth the piece releases reads the mass the case closes: what fell and
    left, plus what the state keeps, is what the storm brought.
    """
    rates = np.asarray(rates_m_per_s, dtype=float)
    durations = np.asarray(durations_s, dtype=float)
    if rates.size != durations.size:
        raise ValueError(f"{rates.size} rates and {durations.size} durations: one per piece.")
    stored = reference_run(rates, durations, 0.0, tau_seconds)
    released = rates * durations - (stored - np.concatenate(([0.0], stored[:-1])))
    return stored, released
