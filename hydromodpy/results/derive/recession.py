"""Recession rate against discharge, on the Brutsaert-Nieber log-log plane.

A draining aquifer sets how fast its own baseflow falls, so ``-dQ/dt`` against
``Q`` collapses every recession of a chronicle onto one cloud whose slope is
the drainage law. The late-time solution of the non-linear Boussinesq (1904)
equation predicts ``-dQ/dt = a Q^b`` with ``b = 3/2`` and

    a = 4.804 K^(1/2) L / (f A^(3/2))

for an aquifer of area ``A`` drained through a stream reach of length ``L``,
hydraulic conductivity ``K`` and drainable porosity ``f``.

Everything is computed on a volume-per-day clock: a discharge in m3/s is
converted to m3/day first, so ``K`` is read in m/day and ``a`` comes out in
``day^-1 (m3/day)^-1/2``, the system the coefficient above is written in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from hydromodpy.core.scope import DOMAIN

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

__all__ = [
    "BOUSSINESQ_LATE_TIME_CONSTANT",
    "SECONDS_PER_DAY",
    "brutsaert_nieber_coefficient",
    "budget_outflow_per_day",
    "recession_cloud",
]

SECONDS_PER_DAY = 86400.0
BOUSSINESQ_LATE_TIME_CONSTANT = 4.804
"""Brutsaert-Nieber coefficient of the late-time non-linear Boussinesq solution."""


def brutsaert_nieber_coefficient(
    *, k: float, porosity: float, stream_length: float, area: float, sides: int = 2
) -> float:
    """Return ``a`` of ``-dQ/dt = a Q^(3/2)`` for one aquifer geometry.

    ``k`` in m/day, ``stream_length`` and ``area`` in m and m2, ``porosity``
    dimensionless. The result applies to a discharge expressed in m3/day and a
    time in days.

    The published coefficient is written for a reach drained from both banks,
    with ``area`` the aquifer on both of them. A hillslope draining into one
    bank only carries half the discharge of that symmetric pair for the same
    breadth, which halves the coefficient: declare ``sides = 1`` and give the
    area of the single flank.
    """
    symmetric = BOUSSINESQ_LATE_TIME_CONSTANT * k**0.5 * stream_length / (porosity * area**1.5)
    return symmetric * sides / 2.0


def _days_since_start(index: pd.Index) -> np.ndarray:
    """Return the series index as days elapsed since its first entry."""
    if isinstance(index, pd.DatetimeIndex):
        return np.asarray((index - index[0]).total_seconds(), dtype="float64") / SECONDS_PER_DAY
    return np.asarray(index, dtype="float64")


def budget_outflow_per_day(run: Run, component: str) -> pd.Series:
    """Return what leaves the domain through one budget component, in m3/day.

    A lateral fixed head is not a stream, so the catchment aggregation never
    turns it into a ``discharge`` series: on a hillslope closed by a fixed head
    the recession is only readable in the budget itself. Rows are taken on the
    whole-domain zone and indexed by the run's own time axis.
    """
    rows = run.budget(component=component)
    if rows.empty:
        raise ValueError(f"budget component '{component}' is empty for sim {run.sim_id}")
    zone = DOMAIN if (rows["zone_id"] == DOMAIN).any() else rows["zone_id"].iloc[0]
    zoned = rows.loc[rows["zone_id"] == zone]
    steps = np.asarray(zoned["timestep"], dtype="int64")
    values = np.asarray(zoned["flux_out"], dtype="float64") * SECONDS_PER_DAY
    order = np.argsort(steps)
    steps, values = steps[order], values[order]
    index = run.time_index
    return pd.Series(values, index=index[steps] if len(index) > steps.max() else steps)


def recession_cloud(discharge: pd.Series, *, skip: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(Q, -dQ/dt)`` over the falling limbs of ``discharge``.

    A centered difference would mix a rise and a fall inside one estimate, so
    the rate is the step difference taken at the midpoint of the step, kept
    only where it is negative: a rising limb carries no recession. ``skip``
    drops the head of the chronicle, where the forcing that built the mound is
    still acting and the aquifer is not yet the only thing draining.
    """
    values = np.asarray(discharge.to_numpy(), dtype="float64")[skip:]
    days = _days_since_start(discharge.index)[skip:]
    if values.size < 3:
        return np.empty(0), np.empty(0)

    dt = np.diff(days)
    rate = np.divide(np.diff(values), dt, out=np.full(values.size - 1, np.nan), where=dt > 0.0)
    mid = 0.5 * (values[:-1] + values[1:])
    keep = np.isfinite(rate) & np.isfinite(mid) & (rate < 0.0) & (mid > 0.0)
    return mid[keep], -rate[keep]
