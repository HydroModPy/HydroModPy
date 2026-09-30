"""Daily soil reservoir, vectorised over columns, looped over days.

Each day the rain reaches the soil before it evaporates. ETR falls linearly
below alpha x RU: alpha is 1 - p of FAO-56 (Allen et al. 1998) and LP of HBV
(Seibert and Vis 2012). The water above RU leaves the soil; a linear reservoir
of time constant ``transit_time_days``, integrated exactly over the day, can
delay it. The sealed share of a column runs off; the soil covers the rest.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

RU_TOLERANCE_MM: float = 1e-9  # a soil within this of RU counts as full


@dataclass(frozen=True, slots=True)
class SoilParameters:
    """Parameters of the soil reservoir; ``ru_mm`` has one value per column."""

    ru_mm: np.ndarray  # (N,) float64, >= 0
    alpha: float  # (0, 1]
    kc: float  # [0, 2]
    impervious_fraction: float  # [0, 1)
    bypass_fraction: float  # [0, 1)
    transit_time_days: float  # [0, 30]


@dataclass(frozen=True, slots=True)
class SoilState:
    """Stores of the unsealed share, in mm per unit of unsealed area."""

    soil_mm: np.ndarray  # (N,)
    transit_mm: np.ndarray  # (N,)


@dataclass(frozen=True, slots=True)
class SoilDay:
    """One day of fluxes, in mm per unit of column area."""

    etr: np.ndarray  # (N,)
    residual_etp: np.ndarray  # (N,)
    recharge: np.ndarray  # (N,) sent to MODFLOW
    runoff: np.ndarray  # (N,) sealed share


@dataclass(frozen=True, slots=True)
class SoilFluxes:
    """A run of days, in mm/day and mm per unit of column area."""

    etr: np.ndarray  # (T, N)
    residual_etp: np.ndarray  # (T, N)
    recharge: np.ndarray  # (T, N)
    runoff: np.ndarray  # (T, N)
    soil_storage: np.ndarray  # (T, N) end of day
    transit_storage: np.ndarray  # (T, N) end of day
    soil_storage_start: np.ndarray  # (N,) before the first day
    transit_storage_start: np.ndarray  # (N,) before the first day
    end: SoilState  # state after the last day, unsealed units


@dataclass(frozen=True, slots=True)
class Spinup:
    """Where the repeated first year left the soil."""

    state: SoilState
    cycles: int  # repetitions run, >= 1
    settled: bool
    last_change_mm: float  # max over columns of the last change, soil or transit
    never_full: np.ndarray  # (N,) bool, soil below RU on every day of the last cycle


@dataclass(frozen=True, slots=True)
class AnnualSoilBudget:
    """Totals per calendar year, in mm over the days of that year in the run."""

    years: np.ndarray  # (Y,) int
    days: np.ndarray  # (Y,) int
    precipitation: np.ndarray  # (Y, N)
    etp: np.ndarray  # (Y, N) as loaded, before kc
    etr: np.ndarray  # (Y, N)
    residual_etp: np.ndarray  # (Y, N)
    recharge: np.ndarray  # (Y, N)
    runoff: np.ndarray  # (Y, N)
    soil_storage_change: np.ndarray  # (Y, N)
    transit_storage_change: np.ndarray  # (Y, N)
    residual: np.ndarray  # (Y, N)
    weights: np.ndarray  # (N,) weight of each column in the basin value

    def basin(self, name: str) -> np.ndarray:
        """Return ``sum_n weights[n] * <name>[:, n]``, shape (Y,)."""
        return getattr(self, name) @ self.weights


def full_soil(params: SoilParameters) -> SoilState:
    """Soil at field capacity, transit store empty: the wet-winter start."""
    return SoilState(
        soil_mm=params.ru_mm.copy(),
        transit_mm=np.zeros_like(params.ru_mm),
    )


def route_linear_reservoir(
    inflow: np.ndarray, transit_mm: np.ndarray, transit_time_days: float
) -> tuple[np.ndarray, np.ndarray]:
    """Route one day of constant inflow through a linear reservoir of constant k.

    Exact solution of ``dR/dt = inflow - R/k`` over one day: unconditionally
    stable for every ``k > 0``. Returns ``(outflow, new transit_mm)``.
    """
    k = transit_time_days
    decay = np.exp(-1.0 / k)
    new_transit_mm = inflow * k + (transit_mm - inflow * k) * decay
    outflow = inflow - (new_transit_mm - transit_mm)
    return outflow, new_transit_mm


def soil_step(
    state: SoilState, precipitation: np.ndarray, etp: np.ndarray, params: SoilParameters
) -> tuple[SoilState, SoilDay]:
    """Advance the soil and transit stores by one day, column by column.

    The rain reaches the soil before it evaporates (spec section 7). Never
    modifies ``state``, ``precipitation`` or ``etp``: every output is a new
    array.
    """
    ru_mm = params.ru_mm
    alpha = params.alpha
    bypass_fraction = params.bypass_fraction
    transit_time_days = params.transit_time_days
    unsealed_fraction = 1.0 - params.impervious_fraction

    runoff = params.impervious_fraction * precipitation
    bypassed = bypass_fraction * precipitation
    wet_soil = state.soil_mm + (1.0 - bypass_fraction) * precipitation
    demand = params.kc * etp

    ratio = np.ones_like(wet_soil)
    has_capacity = ru_mm > 0
    ratio[has_capacity] = np.minimum(1.0, wet_soil[has_capacity] / (alpha * ru_mm[has_capacity]))

    etr_soil = np.minimum(wet_soil, demand * ratio)
    wet_soil = wet_soil - etr_soil
    soil_excess = np.maximum(0.0, wet_soil - ru_mm)
    soil_mm = wet_soil - soil_excess
    inflow_to_transit = soil_excess + bypassed

    if transit_time_days == 0.0:
        outflow = inflow_to_transit
        transit_mm = state.transit_mm
    else:
        outflow, transit_mm = route_linear_reservoir(
            inflow_to_transit, state.transit_mm, transit_time_days
        )

    day = SoilDay(
        etr=unsealed_fraction * etr_soil,
        residual_etp=unsealed_fraction * (demand - etr_soil),
        recharge=unsealed_fraction * outflow,
        runoff=runoff,
    )
    return SoilState(soil_mm=soil_mm, transit_mm=transit_mm), day


def run_soil_balance(
    precipitation: np.ndarray, etp: np.ndarray, params: SoilParameters, initial: SoilState
) -> SoilFluxes:
    """Run the soil day by day, preallocating every output array."""
    n_days, n_columns = precipitation.shape
    etr = np.empty((n_days, n_columns), dtype=np.float64)
    residual_etp = np.empty((n_days, n_columns), dtype=np.float64)
    recharge = np.empty((n_days, n_columns), dtype=np.float64)
    runoff = np.empty((n_days, n_columns), dtype=np.float64)
    soil_storage = np.empty((n_days, n_columns), dtype=np.float64)
    transit_storage = np.empty((n_days, n_columns), dtype=np.float64)

    unsealed_fraction = 1.0 - params.impervious_fraction
    state = initial
    for t in range(n_days):
        state, day = soil_step(state, precipitation[t], etp[t], params)
        etr[t] = day.etr
        residual_etp[t] = day.residual_etp
        recharge[t] = day.recharge
        runoff[t] = day.runoff
        soil_storage[t] = unsealed_fraction * state.soil_mm
        transit_storage[t] = unsealed_fraction * state.transit_mm

    return SoilFluxes(
        etr=etr,
        residual_etp=residual_etp,
        recharge=recharge,
        runoff=runoff,
        soil_storage=soil_storage,
        transit_storage=transit_storage,
        soil_storage_start=unsealed_fraction * initial.soil_mm,
        transit_storage_start=unsealed_fraction * initial.transit_mm,
        end=state,
    )


def spinup_state(
    precipitation: np.ndarray,
    etp: np.ndarray,
    params: SoilParameters,
    *,
    tol_mm: float = 0.1,
    max_cycles: int = 20,
) -> Spinup:
    """Repeat the first year of ``precipitation``/``etp`` until the soil settles.

    Starts full (`full_soil`), then runs the same days again through
    `soil_step` until the end-of-cycle soil and transit stores move by less
    than ``tol_mm``, or ``max_cycles`` is reached.
    """
    n_days = precipitation.shape[0]
    state = full_soil(params)
    previous_soil_end = state.soil_mm
    previous_transit_end = state.transit_mm
    settled = False
    change = float("inf")
    cycles_run = 0
    last_cycle_soil = np.empty_like(precipitation)

    for cycle in range(1, max_cycles + 1):
        cycles_run = cycle
        for t in range(n_days):
            state, _ = soil_step(state, precipitation[t], etp[t], params)
            last_cycle_soil[t] = state.soil_mm
        change = float(
            np.max(
                np.maximum(
                    np.abs(state.soil_mm - previous_soil_end),
                    np.abs(state.transit_mm - previous_transit_end),
                )
            )
        )
        if change < tol_mm:
            settled = True
            break
        previous_soil_end = state.soil_mm
        previous_transit_end = state.transit_mm

    has_capacity = params.ru_mm > 0
    stayed_below_ru = np.all(last_cycle_soil < params.ru_mm - RU_TOLERANCE_MM, axis=0)
    never_full = has_capacity & stayed_below_ru

    return Spinup(
        state=state,
        cycles=cycles_run,
        settled=settled,
        last_change_mm=change,
        never_full=never_full,
    )


def balance_residual(precipitation: np.ndarray, fluxes: SoilFluxes) -> np.ndarray:
    """Mass-balance residual, column units: should stay near machine precision."""
    previous_soil = np.concatenate(
        [fluxes.soil_storage_start[np.newaxis, :], fluxes.soil_storage[:-1]], axis=0
    )
    previous_transit = np.concatenate(
        [fluxes.transit_storage_start[np.newaxis, :], fluxes.transit_storage[:-1]], axis=0
    )
    soil_change = fluxes.soil_storage - previous_soil
    transit_change = fluxes.transit_storage - previous_transit
    return (
        precipitation - fluxes.etr - fluxes.recharge - fluxes.runoff - soil_change - transit_change
    )


def annual_budget(
    years: np.ndarray,
    precipitation: np.ndarray,
    etp: np.ndarray,
    fluxes: SoilFluxes,
    weights: np.ndarray,
) -> AnnualSoilBudget:
    """Sum every daily quantity over the calendar years ``years`` names."""
    daily_residual = balance_residual(precipitation, fluxes)
    unique_years = np.unique(years)
    n_years = unique_years.shape[0]
    n_columns = precipitation.shape[1]

    days = np.empty(n_years, dtype=np.int64)
    precipitation_sum = np.empty((n_years, n_columns), dtype=np.float64)
    etp_sum = np.empty((n_years, n_columns), dtype=np.float64)
    etr_sum = np.empty((n_years, n_columns), dtype=np.float64)
    residual_etp_sum = np.empty((n_years, n_columns), dtype=np.float64)
    recharge_sum = np.empty((n_years, n_columns), dtype=np.float64)
    runoff_sum = np.empty((n_years, n_columns), dtype=np.float64)
    soil_storage_change = np.empty((n_years, n_columns), dtype=np.float64)
    transit_storage_change = np.empty((n_years, n_columns), dtype=np.float64)
    residual_sum = np.empty((n_years, n_columns), dtype=np.float64)

    for i, year in enumerate(unique_years):
        day_indices = np.flatnonzero(years == year)
        days[i] = day_indices.size
        precipitation_sum[i] = precipitation[day_indices].sum(axis=0)
        etp_sum[i] = etp[day_indices].sum(axis=0)
        etr_sum[i] = fluxes.etr[day_indices].sum(axis=0)
        residual_etp_sum[i] = fluxes.residual_etp[day_indices].sum(axis=0)
        recharge_sum[i] = fluxes.recharge[day_indices].sum(axis=0)
        runoff_sum[i] = fluxes.runoff[day_indices].sum(axis=0)
        residual_sum[i] = daily_residual[day_indices].sum(axis=0)

        first_day, last_day = day_indices[0], day_indices[-1]
        soil_before_year = (
            fluxes.soil_storage_start if first_day == 0 else fluxes.soil_storage[first_day - 1]
        )
        transit_before_year = (
            fluxes.transit_storage_start
            if first_day == 0
            else fluxes.transit_storage[first_day - 1]
        )
        soil_storage_change[i] = fluxes.soil_storage[last_day] - soil_before_year
        transit_storage_change[i] = fluxes.transit_storage[last_day] - transit_before_year

    return AnnualSoilBudget(
        years=unique_years,
        days=days,
        precipitation=precipitation_sum,
        etp=etp_sum,
        etr=etr_sum,
        residual_etp=residual_etp_sum,
        recharge=recharge_sum,
        runoff=runoff_sum,
        soil_storage_change=soil_storage_change,
        transit_storage_change=transit_storage_change,
        residual=residual_sum,
        weights=weights,
    )
