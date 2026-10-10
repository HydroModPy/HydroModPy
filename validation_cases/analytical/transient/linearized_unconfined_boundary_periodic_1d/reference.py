"""Ferris (1951) tidal reference for the 1D linearized unconfined boundary-periodic case.

A semi-infinite aquifer of transmissivity ``T`` and storativity ``S`` is bounded
at ``x = 0`` by a sea whose level oscillates as ``h0 + A cos(2 pi t / t0)``.
Once the start-up transient has died, the head is

    h(x, t) = h0 + A exp(-x / lam) cos(2 pi t / t0 - x / lam),
    lam = sqrt(t0 T / (pi S)).

The amplitude decays by ``e`` and the phase lags by one radian over each
damping length ``lam``. The case starts at high tide: the start-up transient
then has no first moment and decays as ``t**-2``, not ``t**-1``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SECONDS_PER_DAY = 86400.0


def damping_length_m(
    *,
    hydraulic_conductivity_m_per_s: float,
    reference_saturated_thickness_m: float,
    specific_yield: float,
    tide_period_seconds: float,
) -> float:
    """Return the length ``sqrt(t0 T / (pi S))`` over which the tide decays by ``e``."""
    transmissivity = float(hydraulic_conductivity_m_per_s) * float(reference_saturated_thickness_m)
    return float(
        np.sqrt(float(tide_period_seconds) * transmissivity / (np.pi * float(specific_yield)))
    )


def ferris_tidal_profiles(
    *,
    x,
    eval_times_seconds,
    mean_sea_level_m: float,
    tide_amplitude_m: float,
    tide_period_seconds: float,
    damping_length: float,
) -> np.ndarray:
    """Return the Ferris head, one row per time and one column per ``x`` from the sea.

    ``x`` is the distance from where the model holds the sea level. A negative
    distance is clipped to the sea.
    """
    distance = np.maximum(np.asarray(x, dtype=float).reshape(-1), 0.0) / float(damping_length)
    times = np.asarray(eval_times_seconds, dtype=float).reshape(-1)
    omega_t = 2.0 * np.pi * times / float(tide_period_seconds)
    return float(mean_sea_level_m) + float(tide_amplitude_m) * np.exp(-distance)[None, :] * np.cos(
        omega_t[:, None] - distance[None, :]
    )


def tide_period_means(
    *,
    period_start_seconds,
    period_length_seconds: float,
    mean_sea_level_m: float,
    tide_amplitude_m: float,
    tide_period_seconds: float,
) -> np.ndarray:
    """Return the mean sea level over each period ``[start, start + length)``.

    This is what a model holds over one stress period when it reads the tide
    as period means, as a tide gauge publishes hourly means.
    """
    starts = np.asarray(period_start_seconds, dtype=float).reshape(-1)
    omega = 2.0 * np.pi / float(tide_period_seconds)
    length = float(period_length_seconds)
    mean_cos = (np.sin(omega * (starts + length)) - np.sin(omega * starts)) / (omega * length)
    return float(mean_sea_level_m) + float(tide_amplitude_m) * mean_cos


def period_mean_levels_from_csv(
    path,
    *,
    start: str,
    period_length_seconds: float,
    nper: int,
) -> np.ndarray:
    """Return the mean of the CSV samples stamped in each stress period.

    This is the ``aggregate = "mean"`` rule the launcher applies to a side
    head chronicle: a period takes the mean of the samples stamped in
    ``[start, end)``.
    """
    frame = pd.read_csv(path, parse_dates=["date"])
    stamps = (frame["date"] - pd.Timestamp(start)).dt.total_seconds().to_numpy(dtype=float)
    values = frame["value"].to_numpy(dtype=float)
    period_index = np.floor(stamps / float(period_length_seconds)).astype(int)
    levels = np.empty(int(nper), dtype=float)
    for period in range(int(nper)):
        inside = period_index == period
        if not np.any(inside):
            raise ValueError(f"{path}: no sample in stress period {period}.")
        levels[period] = float(values[inside].mean())
    return levels


def fit_tidal_harmonic(
    *,
    times_seconds,
    values: np.ndarray,
    tide_period_seconds: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Fit ``c + a cos(w t) + b sin(w t)`` to each column by least squares.

    ``values`` has one row per time. Returns the amplitude ``sqrt(a**2 + b**2)``
    and the phase lag ``atan2(b, a)`` in radians of each column, the lag behind
    ``cos(w t)``. The times should span whole tide periods.
    """
    times = np.asarray(times_seconds, dtype=float).reshape(-1)
    data = np.asarray(values, dtype=float).reshape(times.size, -1)
    omega = 2.0 * np.pi / float(tide_period_seconds)
    design = np.column_stack([np.ones_like(times), np.cos(omega * times), np.sin(omega * times)])
    coefficients, *_ = np.linalg.lstsq(design, data, rcond=None)
    cos_part, sin_part = coefficients[1], coefficients[2]
    return np.hypot(cos_part, sin_part), np.arctan2(sin_part, cos_part)


__all__ = [
    "damping_length_m",
    "ferris_tidal_profiles",
    "fit_tidal_harmonic",
    "period_mean_levels_from_csv",
    "tide_period_means",
]
