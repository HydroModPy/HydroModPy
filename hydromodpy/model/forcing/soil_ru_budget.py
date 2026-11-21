"""The soil capacity that closes the multi-year water budget against the gauge.

Over several years the water that leaves the soil, recharge plus runoff, has to
match what the gauge measures, give or take the storage of the aquifer and its
own evaporation. The recharge falls when the capacity ``ru`` grows, so one value
of ``ru`` closes that budget. This module finds it by bisection on the soil
alone, without MODFLOW, so ``ru`` can be fixed before K and Sy are calibrated.

A single year says nothing (on the Nancon, 2000-2020, the yearly value spans 21
to 800 mm), so the module also gives the spread of the answer when the years
are drawn again at random, and how far a 5 % bias of the rain or of the gauge
moves it. The value is an effective capacity: it absorbs the biases of the
forcing, and it is not a property of the soil.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from hydromodpy.model.forcing.soil_forcing import SoilForcings, basin_water_out

RU_SEARCH_MM: tuple[float, float] = (0.0, 1000.0)
"""The capacities searched, the range the soil section accepts."""

RU_NODES_MM: tuple[float, ...] = (0.0, 50.0, 100.0, 150.0, 200.0, 300.0, 400.0, 600.0, 1000.0)
"""Capacities run once for the resampled years and the gauge bias."""

BISECTION_TOLERANCE_MM = 0.5
MIN_GAUGED_YEARS = 2
GAUGED_SHARE_OF_A_YEAR = 0.9
RESAMPLES = 1000


@dataclass(frozen=True)
class RuClosure:
    """The capacity that closes the budget, its spread, and why it is missing."""

    ru_mm: float | None
    reason: str | None  # why ru_mm is None
    years: int  # calendar years with the gauge on 90 % of their days
    band_mm: tuple[float, float] | None  # 5 and 95 % over resampled years
    rain_minus_5_mm: float | None
    rain_plus_5_mm: float | None
    gauge_minus_5_mm: float | None
    gauge_plus_5_mm: float | None
    per_10_mm_evaporation_mm: float | None  # change of ru for 10 mm/year more evaporation


def _missing(reason: str, years: int = 0) -> RuClosure:
    return RuClosure(None, reason, years, None, None, None, None, None, None)


def _gauged_years(days: np.ndarray, gauged: np.ndarray) -> np.ndarray:
    """Calendar year of each day, kept only for years gauged on 90 % of their days."""
    years = pd.DatetimeIndex(days).year.to_numpy()
    keep = np.zeros(days.shape, dtype=bool)
    for year in np.unique(years):
        in_year = years == year
        days_in_year = 366 if pd.Timestamp(year=int(year), month=1, day=1).is_leap_year else 365
        if np.sum(in_year & np.isfinite(gauged)) >= GAUGED_SHARE_OF_A_YEAR * days_in_year:
            keep |= in_year
    return np.where(keep & np.isfinite(gauged), years, -1)


def _bisect(
    forcings: SoilForcings, target: float, used: np.ndarray, *, precipitation_scale: float = 1.0
) -> float | None:
    """The ``ru`` whose mean water out over ``used`` days equals ``target`` mm/day, or None."""

    def mean_out(ru: float) -> float:
        out = basin_water_out(forcings, ru, precipitation_scale=precipitation_scale)
        if out is None:
            return float("nan")
        return float(np.mean((out[0] + out[1])[used]))

    # A large soil may never repeat its first year, so the search stops at the
    # largest node whose spin-up settles.
    low, out_low = RU_SEARCH_MM[0], mean_out(RU_SEARCH_MM[0])
    if not np.isfinite(out_low) or target > out_low:
        return None
    high = None
    for node in RU_NODES_MM[1:]:
        out_node = mean_out(node)
        if not np.isfinite(out_node):
            break
        if out_node <= target:
            high = node
            break
        low = node
    if high is None:
        return None
    while high - low > BISECTION_TOLERANCE_MM:
        middle = 0.5 * (low + high)
        out_middle = mean_out(middle)
        if not np.isfinite(out_middle):
            return None
        if out_middle > target:
            low = middle
        else:
            high = middle
    return 0.5 * (low + high)


def _crossing(ru_nodes: np.ndarray, out_nodes: np.ndarray, target: float) -> float | None:
    """Where the decreasing curve ``out_nodes`` of ``ru_nodes`` meets ``target``, linearly."""
    if not out_nodes[-1] <= target <= out_nodes[0]:
        return None
    # np.interp reads an increasing abscissa, so the curve is read backwards.
    return float(np.interp(target, out_nodes[::-1], ru_nodes[::-1]))


def ru_closing_budget(forcings: SoilForcings, gauged_mm_per_day: np.ndarray) -> RuClosure:
    """Find the ``ru`` that closes recharge + runoff against the gauge, with its spread.

    ``gauged_mm_per_day`` is the gauged discharge over the catchment area on the
    days of ``forcings``, NaN where the gauge has no value. Only the calendar
    years gauged on 90 % of their days count, and only their gauged days.
    """
    year_of_day = _gauged_years(forcings.days, gauged_mm_per_day)
    used = year_of_day >= 0
    years = np.unique(year_of_day[used])
    if years.size < MIN_GAUGED_YEARS:
        return _missing(
            f"the gauge covers {years.size} calendar year(s) on 90 % of their days, "
            f"and a budget needs {MIN_GAUGED_YEARS} at least",
            int(years.size),
        )
    target = float(np.mean(gauged_mm_per_day[used]))

    ru = _bisect(forcings, target, used)
    if ru is None:
        return _missing(
            f"no capacity between {RU_SEARCH_MM[0]:g} and {RU_SEARCH_MM[1]:g} mm closes "
            f"the budget on a gauge of {target * 365.25:.0f} mm/year: the soil gives "
            "more water at the largest capacity whose first year repeats, or less at "
            "0 mm; check the rain and the catchment area",
            int(years.size),
        )

    ru_nodes = np.asarray(RU_NODES_MM)
    yearly_out = np.full((years.size, ru_nodes.size), np.nan)
    for k, node in enumerate(ru_nodes):
        out = basin_water_out(forcings, node)
        if out is None:
            continue
        water = out[0] + out[1]
        for i, year in enumerate(years):
            yearly_out[i, k] = water[year_of_day == year].sum()
    settled = np.all(np.isfinite(yearly_out), axis=0)
    ru_nodes, yearly_out = ru_nodes[settled], yearly_out[:, settled]
    yearly_gauge = np.array([gauged_mm_per_day[year_of_day == y].sum() for y in years])
    yearly_days = np.array([np.sum(year_of_day == y) for y in years])

    band = None
    if ru_nodes.size >= 2:
        rng = np.random.default_rng(0)
        draws = []
        for _ in range(RESAMPLES):
            pick = rng.integers(0, years.size, years.size)
            n_days = yearly_days[pick].sum()
            out_nodes = yearly_out[pick].sum(axis=0) / n_days
            value = _crossing(ru_nodes, out_nodes, yearly_gauge[pick].sum() / n_days)
            if value is not None:
                draws.append(value)
        if draws:
            band = (float(np.percentile(draws, 5)), float(np.percentile(draws, 95)))

    mean_nodes = yearly_out.sum(axis=0) / yearly_days.sum()
    per_10 = None
    gauge_low = gauge_high = None
    if ru_nodes.size >= 2:
        gauge_low = _crossing(ru_nodes, mean_nodes, 0.95 * target)
        gauge_high = _crossing(ru_nodes, mean_nodes, 1.05 * target)
        shifted = _crossing(ru_nodes, mean_nodes, target + 10.0 / 365.25)
        central = _crossing(ru_nodes, mean_nodes, target)
        if shifted is not None and central is not None:
            per_10 = shifted - central

    return RuClosure(
        ru_mm=ru,
        reason=None,
        years=int(years.size),
        band_mm=band,
        rain_minus_5_mm=_bisect(forcings, target, used, precipitation_scale=0.95),
        rain_plus_5_mm=_bisect(forcings, target, used, precipitation_scale=1.05),
        gauge_minus_5_mm=gauge_low,
        gauge_plus_5_mm=gauge_high,
        per_10_mm_evaporation_mm=per_10,
    )


__all__ = ["RuClosure", "ru_closing_budget"]
