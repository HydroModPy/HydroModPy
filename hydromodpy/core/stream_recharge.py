"""The mean recharge the stream-network criterion divides by.

The criterion thresholds seepage at a fraction of the recharge and calibrates
``K/R``, so ``R`` has one definition for the trials that score a run and for
the figures that redraw it: the time mean over the run's periods, each weighted
by its length like ``first_clim = "mean"``, of the rate the recharge forcing gives
each period, itself averaged over the cells by their area.

A period's rate is its own. A solver writes the record mean into a steady
spin-up period in place of that period's rate, and a mean read from what it
wrote is another statistic: on the monthly Nancon, 8.634e-9 m/s where the
forcing gives 9.062e-9, and the steady phase that seeds the run reads 9.062e-9.
So the trials read the rates the built model holds. A run keeps that number on
its ``forcing`` group, and the redraw reads it back. A run that kept none
rebuilds the rates from the station forcing it stores, and both average them here.

It lives in ``core`` because the calibration and the results layers both need
it and neither may import the other.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.time.period_aggregation import period_mean_on_index

__all__ = (
    "CRITERION_MEAN_RECHARGE_ATTR",
    "criterion_mean_recharge",
    "forcing_period_rates",
    "mean_recharge_m_s",
)

# Attribute of the ``forcing`` group: the mean recharge of the run, in m/s.
CRITERION_MEAN_RECHARGE_ATTR = "criterion_mean_recharge_m_s"


def forcing_period_rates(samples: pd.Series, edges: Any) -> np.ndarray:
    """Return the rate a recharge series gives each period ``[s, e)``.

    The rule the solver forcing is built by: the mean of the samples in the
    period, else the last sample before its end. A negative rate is clipped at
    zero, as the recharge package receives it: the deficit goes to EVT.
    ``edges`` are the ``n + 1`` period edges; the result keeps the unit of
    ``samples``.
    """
    bounds = pd.DatetimeIndex(pd.to_datetime(edges))
    if len(bounds) < 2:
        raise ValueError(f"a run needs at least two period edges, got {len(bounds)}.")
    series = pd.Series(samples, dtype="float64").dropna()
    series.index = pd.DatetimeIndex(series.index)
    series = series.sort_index()
    rates = period_mean_on_index(series, bounds[1:], start=bounds[0]).to_numpy(dtype=float)
    for index in np.flatnonzero(~np.isfinite(rates)):
        before = series[series.index < bounds[index + 1]]
        if len(before):
            rates[index] = float(before.iloc[-1])
    return np.maximum(rates, 0.0)


def criterion_mean_recharge(values: Any, *, areas: Any = None, durations: Any = None) -> float:
    """Return the mean recharge rate of a run: the periods by length, the cells by area.

    ``values`` is one array or a sequence of one entry per period, a number or an
    array. An entry sized like ``areas`` holds one rate per cell and takes their
    area-weighted mean, so the refined cells of a mesh do not outweigh the coarse
    ones. Any other entry takes its plain mean. ``durations`` holds the length of
    each entry; without it, each entry counts once. A non-finite rate carries no
    weight.
    """
    parts = values if isinstance(values, list | tuple) else [values]
    cell_areas = None if areas is None else np.asarray(areas, dtype=float).reshape(-1)
    lengths = np.ones(len(parts)) if durations is None else np.asarray(durations, dtype=float)
    if lengths.size != len(parts):
        raise ValueError(f"{len(parts)} recharge entries need {len(parts)} lengths.")
    rates: list[float] = []
    weights: list[float] = []
    for part, length in zip(parts, lengths.reshape(-1), strict=True):
        flat = np.asarray(part, dtype=float).reshape(-1)
        usable = np.isfinite(flat)
        if cell_areas is not None and flat.size == cell_areas.size:
            usable &= np.isfinite(cell_areas) & (cell_areas > 0.0)
            if np.any(usable):
                rates.append(float(np.average(flat[usable], weights=cell_areas[usable])))
                weights.append(float(length))
        elif np.any(usable):
            rates.append(float(np.mean(flat[usable])))
            weights.append(float(length))
    if not rates:
        raise ValueError("the recharge holds no finite rate.")
    return float(np.average(rates, weights=weights))


def _rates_with_their_lengths(
    recharge: Any, perlen: Any, areas: Any
) -> tuple[list[Any], np.ndarray | None]:
    """Return the entries of a recharge the model holds and the length of each.

    A table gives one entry per period it states. A payload sized like the cells
    stands for every period at once; one with a leading entry per period gives each
    its rate. Any other payload is one record whose values have no known length.
    """
    lengths = None if perlen is None else np.asarray(perlen, dtype=float).reshape(-1)
    if isinstance(recharge, dict):
        periods = sorted(recharge)
        return [recharge[k] for k in periods], None if lengths is None else lengths[periods]
    flat = np.asarray(recharge, dtype=float)
    holds_cell_rates = areas is not None and flat.size == np.size(areas)
    one_entry_per_period = lengths is not None and flat.ndim >= 1 and flat.shape[0] == lengths.size
    if one_entry_per_period and lengths.size > 1 and not holds_cell_rates:
        return list(flat), lengths
    return [recharge], None


def mean_recharge_m_s(model: Any) -> float:
    """Read the mean recharge back from the built model, not from the TOML.

    Unit conversion and spatial distribution can diverge between what a user
    wrote and what the solver received, and the calibrated ratio is only a
    ratio if the recharge that divides it is the one the model actually used.

    A station forcing is held as the rate it gives each period, a steady
    spin-up period at its own rate: the solver writes the record mean there
    only when it writes the package. A gridded forcing is held per cell as the
    solver writes it.
    """
    recharge = getattr(model, "recharge", None)
    if recharge is None:
        raise ValueError(
            "the built model declares no recharge, so the specific seepage threshold "
            "and the K/R ratio have no denominator."
        )
    solver_mesh = getattr(model, "solver_mesh", None)
    # A list or a series holds one rate per period, whatever its length.
    holds_cells = isinstance(recharge, dict | np.ndarray) and solver_mesh is not None
    areas = solver_mesh.cell_areas() if holds_cells else None
    periods, durations = _rates_with_their_lengths(recharge, getattr(model, "perlen", None), areas)
    try:
        return criterion_mean_recharge(periods, areas=areas, durations=durations)
    except ValueError as exc:
        raise ValueError("the recharge the model holds is not a finite number.") from exc
