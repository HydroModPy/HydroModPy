"""Daily soil reservoir, vectorised over columns, looped over days.

Each day the rain reaches the soil before it evaporates. ETR falls linearly
below alpha x RU: alpha is 1 - p of FAO-56 (Allen et al. 1998) and LP of HBV
(Seibert and Vis 2012). The water above RU leaves the soil; a linear reservoir
of time constant ``transit_time_days``, integrated exactly over the day, can
delay it. The sealed share of a column runs off, and so does an optional
SCS-CN share of the unsealed rain (HELP, Schroeder et al. 1994), routed
through its own linear reservoir of time constant ``runoff_time_days``. A
pure delay of ``runoff_lag_days``, applied after that reservoir, then holds
the routed share for a fixed travel time before it joins the discharge. The
soil covers the rest.
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
    curve_number: float | None = None  # AMC II curve number, [30, 98]; None turns the term off
    runoff_time_days: float = 1.0  # time constant of the curve-number runoff reservoir, [0, 10]
    runoff_lag_days: float = 0.0  # pure delay after that reservoir, [0, 5]; 0 costs nothing


@dataclass(frozen=True, slots=True)
class SoilState:
    """Stores of the unsealed share, in mm per unit of unsealed area."""

    soil_mm: np.ndarray  # (N,)
    transit_mm: np.ndarray  # (N,)
    cn_storage_mm: np.ndarray | None = None  # (N,) curve-number routing store; None reads as zero


@dataclass(frozen=True, slots=True)
class SoilDay:
    """One day of fluxes, in mm per unit of column area."""

    etr: np.ndarray  # (N,)
    residual_etp: np.ndarray  # (N,)
    recharge: np.ndarray  # (N,) sent to MODFLOW
    runoff: np.ndarray  # (N,) sealed share plus routed curve-number runoff
    runoff_cn: np.ndarray  # (N,) the curve-number share of runoff alone


@dataclass(frozen=True, slots=True)
class SoilFluxes:
    """A run of days, in mm/day and mm per unit of column area."""

    etr: np.ndarray  # (T, N)
    residual_etp: np.ndarray  # (T, N)
    recharge: np.ndarray  # (T, N)
    runoff: np.ndarray  # (T, N)
    runoff_cn: np.ndarray  # (T, N) curve-number share of runoff
    soil_storage: np.ndarray  # (T, N) end of day
    transit_storage: np.ndarray  # (T, N) end of day
    cn_storage: np.ndarray  # (T, N) end of day
    lag_storage: np.ndarray  # (T, N) end of day; mass delayed but not yet released
    soil_storage_start: np.ndarray  # (N,) before the first day
    transit_storage_start: np.ndarray  # (N,) before the first day
    cn_storage_start: np.ndarray  # (N,) before the first day
    lag_storage_start: np.ndarray  # (N,) before the first day, always 0
    end: SoilState  # state after the last day, unsealed units


@dataclass(frozen=True, slots=True)
class Spinup:
    """Where the repeated first year left the soil."""

    state: SoilState
    cycles: int  # repetitions run, >= 1
    settled: bool
    last_change_mm: float  # max over columns of the last change, soil or transit
    never_full: np.ndarray  # (N,) bool, soil below RU on every day of the last cycle
    last_cycle_runoff_cn: np.ndarray  # (n_days, N) routed, pre-lag CN runoff of the settled cycle


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
    runoff_cn: np.ndarray  # (Y, N) curve-number share of runoff
    soil_storage_change: np.ndarray  # (Y, N)
    transit_storage_change: np.ndarray  # (Y, N)
    cn_storage_change: np.ndarray  # (Y, N)
    lag_storage_change: np.ndarray  # (Y, N)
    residual: np.ndarray  # (Y, N)
    weights: np.ndarray  # (N,) weight of each column in the basin value

    def basin(self, name: str) -> np.ndarray:
        """Return ``sum_n weights[n] * <name>[:, n]``, shape (Y,)."""
        return getattr(self, name) @ self.weights


def full_soil(params: SoilParameters) -> SoilState:
    """Soil at field capacity, transit and curve-number stores empty: the wet-winter start."""
    return SoilState(
        soil_mm=params.ru_mm.copy(),
        transit_mm=np.zeros_like(params.ru_mm),
        cn_storage_mm=np.zeros_like(params.ru_mm),
    )


def retention_mm(cn: float, w: np.ndarray) -> np.ndarray:
    """SCS retention ``S``, mm, at each column's soil wetness ``w`` (0 to 1).

    ``w = 0`` reads the dry-soil retention (AMC I), ``w = 1`` the wet-soil one
    (AMC III), linear between the two (HELP eq. 26; AMC I/III from AMC II,
    Chow, Maidment and Mays 1988, eq. 5.5.6-5.5.7).
    """
    cn1 = 4.2 * cn / (10.0 - 0.058 * cn)
    cn3 = 23.0 * cn / (10.0 + 0.13 * cn)
    s1 = 25400.0 / cn1 - 254.0
    s3 = 25400.0 / cn3 - 254.0
    return s1 + (s3 - s1) * w


def curve_number_runoff(p: np.ndarray, s: np.ndarray) -> np.ndarray:
    """SCS-CN runoff, mm/day: ``(P - Ia)^2 / (P - Ia + S)`` above ``Ia = 0.2 S``, else 0."""
    ia = 0.2 * s
    excess = p - ia
    return np.where(excess > 0.0, excess * excess / (excess + s), 0.0)


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


def apply_runoff_lag(
    series_mm: np.ndarray, lag_days: float, history_mm: np.ndarray | None = None
) -> np.ndarray:
    """Pure delay of ``lag_days`` on a routed runoff series, column by column.

    A fractional lag ``L = n + f`` interpolates between the series shifted by
    the whole days ``n`` and ``n + 1``: ``(1 - f) * shift(n) + f * shift(n +
    1)``. A day that would read before day 0 takes ``history_mm`` (its last
    rows, closest to day 0 last), or zero past what it covers. The output
    carries the same total as ``series_mm`` except what a positive lag pushes
    past the last day, which this function does not represent.
    """
    if lag_days == 0.0:
        return series_mm
    n_days, n_columns = series_mm.shape
    whole_days = int(np.floor(lag_days))
    fraction = lag_days - whole_days

    def before_day_zero(k: int) -> np.ndarray:
        """``k`` days preceding day 0, chronological order: history then zero."""
        if k == 0:
            return np.zeros((0, n_columns), dtype=np.float64)
        available = 0 if history_mm is None else history_mm.shape[0]
        tail = history_mm[-min(k, available) :] if available > 0 else np.zeros((0, n_columns))
        pad = np.zeros((k - tail.shape[0], n_columns), dtype=np.float64)
        return np.concatenate([pad, tail], axis=0)

    def shifted(k: int) -> np.ndarray:
        return np.concatenate([before_day_zero(k), series_mm], axis=0)[:n_days]

    if fraction == 0.0:
        return shifted(whole_days)
    return (1.0 - fraction) * shifted(whole_days) + fraction * shifted(whole_days + 1)


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
    has_capacity = ru_mm > 0

    if params.curve_number is None:
        q_cn = np.zeros_like(precipitation)
    else:
        w = np.ones_like(precipitation)
        w[has_capacity] = np.clip(state.soil_mm[has_capacity] / ru_mm[has_capacity], 0.0, 1.0)
        q_cn = curve_number_runoff(precipitation, retention_mm(params.curve_number, w))
    infiltrating_rain = precipitation - q_cn

    runoff_impervious = params.impervious_fraction * precipitation
    bypassed = bypass_fraction * infiltrating_rain
    wet_soil = state.soil_mm + (1.0 - bypass_fraction) * infiltrating_rain
    demand = params.kc * etp

    ratio = np.ones_like(wet_soil)
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

    cn_storage_in = state.cn_storage_mm if state.cn_storage_mm is not None else np.zeros_like(q_cn)
    if params.runoff_time_days == 0.0:
        routed_q_cn = q_cn
        cn_storage_mm = cn_storage_in
    else:
        routed_q_cn, cn_storage_mm = route_linear_reservoir(
            q_cn, cn_storage_in, params.runoff_time_days
        )
    runoff_cn = unsealed_fraction * routed_q_cn

    day = SoilDay(
        etr=unsealed_fraction * etr_soil,
        residual_etp=unsealed_fraction * (demand - etr_soil),
        recharge=unsealed_fraction * outflow,
        runoff=runoff_impervious + runoff_cn,
        runoff_cn=runoff_cn,
    )
    return (
        SoilState(soil_mm=soil_mm, transit_mm=transit_mm, cn_storage_mm=cn_storage_mm),
        day,
    )


def run_soil_balance(
    precipitation: np.ndarray,
    etp: np.ndarray,
    params: SoilParameters,
    initial: SoilState,
    *,
    runoff_cn_history_mm: np.ndarray | None = None,
) -> SoilFluxes:
    """Run the soil day by day, preallocating every output array.

    ``runoff_cn_history_mm`` is read only when ``params.runoff_lag_days`` is
    not zero: days of routed, pre-lag CN runoff preceding day 0, most recent
    last, used to delay the first days of the run instead of reading them as
    zero. ``params.runoff_lag_days == 0.0`` costs nothing: every array is
    exactly what it was before this parameter existed.
    """
    n_days, n_columns = precipitation.shape
    etr = np.empty((n_days, n_columns), dtype=np.float64)
    residual_etp = np.empty((n_days, n_columns), dtype=np.float64)
    recharge = np.empty((n_days, n_columns), dtype=np.float64)
    runoff = np.empty((n_days, n_columns), dtype=np.float64)
    runoff_cn = np.empty((n_days, n_columns), dtype=np.float64)
    soil_storage = np.empty((n_days, n_columns), dtype=np.float64)
    transit_storage = np.empty((n_days, n_columns), dtype=np.float64)
    cn_storage = np.empty((n_days, n_columns), dtype=np.float64)

    unsealed_fraction = 1.0 - params.impervious_fraction
    initial_cn_mm = (
        initial.cn_storage_mm
        if initial.cn_storage_mm is not None
        else np.zeros_like(initial.soil_mm)
    )
    state = initial
    for t in range(n_days):
        state, day = soil_step(state, precipitation[t], etp[t], params)
        etr[t] = day.etr
        residual_etp[t] = day.residual_etp
        recharge[t] = day.recharge
        runoff[t] = day.runoff
        runoff_cn[t] = day.runoff_cn
        soil_storage[t] = unsealed_fraction * state.soil_mm
        transit_storage[t] = unsealed_fraction * state.transit_mm
        cn_storage[t] = unsealed_fraction * state.cn_storage_mm

    lag_storage = np.zeros((n_days, n_columns), dtype=np.float64)
    if params.runoff_lag_days != 0.0:
        unlagged_runoff_cn = runoff_cn
        runoff_cn = apply_runoff_lag(
            unlagged_runoff_cn, params.runoff_lag_days, history_mm=runoff_cn_history_mm
        )
        runoff = runoff - unlagged_runoff_cn + runoff_cn
        lag_storage = np.cumsum(unlagged_runoff_cn - runoff_cn, axis=0)

    return SoilFluxes(
        etr=etr,
        residual_etp=residual_etp,
        recharge=recharge,
        runoff=runoff,
        runoff_cn=runoff_cn,
        soil_storage=soil_storage,
        transit_storage=transit_storage,
        cn_storage=cn_storage,
        lag_storage=lag_storage,
        soil_storage_start=unsealed_fraction * initial.soil_mm,
        transit_storage_start=unsealed_fraction * initial.transit_mm,
        cn_storage_start=unsealed_fraction * initial_cn_mm,
        lag_storage_start=np.zeros(n_columns, dtype=np.float64),
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
    than ``tol_mm``, or ``max_cycles`` is reached. Also keeps the settled
    cycle's day-by-day, pre-lag CN runoff: ``runoff_lag_days`` reads its tail
    as the days preceding day 0, the periodic continuation a settled spin-up
    stands for, instead of reading them as zero.
    """
    n_days = precipitation.shape[0]
    state = full_soil(params)
    previous_soil_end = state.soil_mm
    previous_transit_end = state.transit_mm
    previous_cn_end = state.cn_storage_mm
    settled = False
    change = float("inf")
    cycles_run = 0
    last_cycle_soil = np.empty_like(precipitation)
    last_cycle_runoff_cn = np.empty_like(precipitation)

    for cycle in range(1, max_cycles + 1):
        cycles_run = cycle
        for t in range(n_days):
            state, day = soil_step(state, precipitation[t], etp[t], params)
            last_cycle_soil[t] = state.soil_mm
            last_cycle_runoff_cn[t] = day.runoff_cn
        change = float(
            np.max(
                np.maximum(
                    np.abs(state.soil_mm - previous_soil_end),
                    np.maximum(
                        np.abs(state.transit_mm - previous_transit_end),
                        np.abs(state.cn_storage_mm - previous_cn_end),
                    ),
                )
            )
        )
        if change < tol_mm:
            settled = True
            break
        previous_soil_end = state.soil_mm
        previous_transit_end = state.transit_mm
        previous_cn_end = state.cn_storage_mm

    has_capacity = params.ru_mm > 0
    stayed_below_ru = np.all(last_cycle_soil < params.ru_mm - RU_TOLERANCE_MM, axis=0)
    never_full = has_capacity & stayed_below_ru

    return Spinup(
        state=state,
        cycles=cycles_run,
        settled=settled,
        last_change_mm=change,
        never_full=never_full,
        last_cycle_runoff_cn=last_cycle_runoff_cn,
    )


def balance_residual(precipitation: np.ndarray, fluxes: SoilFluxes) -> np.ndarray:
    """Mass-balance residual, column units: should stay near machine precision."""
    previous_soil = np.concatenate(
        [fluxes.soil_storage_start[np.newaxis, :], fluxes.soil_storage[:-1]], axis=0
    )
    previous_transit = np.concatenate(
        [fluxes.transit_storage_start[np.newaxis, :], fluxes.transit_storage[:-1]], axis=0
    )
    previous_cn = np.concatenate(
        [fluxes.cn_storage_start[np.newaxis, :], fluxes.cn_storage[:-1]], axis=0
    )
    previous_lag = np.concatenate(
        [fluxes.lag_storage_start[np.newaxis, :], fluxes.lag_storage[:-1]], axis=0
    )
    soil_change = fluxes.soil_storage - previous_soil
    transit_change = fluxes.transit_storage - previous_transit
    cn_change = fluxes.cn_storage - previous_cn
    lag_change = fluxes.lag_storage - previous_lag
    return (
        precipitation
        - fluxes.etr
        - fluxes.recharge
        - fluxes.runoff
        - soil_change
        - transit_change
        - cn_change
        - lag_change
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
    runoff_cn_sum = np.empty((n_years, n_columns), dtype=np.float64)
    soil_storage_change = np.empty((n_years, n_columns), dtype=np.float64)
    transit_storage_change = np.empty((n_years, n_columns), dtype=np.float64)
    cn_storage_change = np.empty((n_years, n_columns), dtype=np.float64)
    lag_storage_change = np.empty((n_years, n_columns), dtype=np.float64)
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
        runoff_cn_sum[i] = fluxes.runoff_cn[day_indices].sum(axis=0)
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
        cn_before_year = (
            fluxes.cn_storage_start if first_day == 0 else fluxes.cn_storage[first_day - 1]
        )
        lag_before_year = (
            fluxes.lag_storage_start if first_day == 0 else fluxes.lag_storage[first_day - 1]
        )
        soil_storage_change[i] = fluxes.soil_storage[last_day] - soil_before_year
        transit_storage_change[i] = fluxes.transit_storage[last_day] - transit_before_year
        cn_storage_change[i] = fluxes.cn_storage[last_day] - cn_before_year
        lag_storage_change[i] = fluxes.lag_storage[last_day] - lag_before_year

    return AnnualSoilBudget(
        years=unique_years,
        days=days,
        precipitation=precipitation_sum,
        etp=etp_sum,
        etr=etr_sum,
        residual_etp=residual_etp_sum,
        recharge=recharge_sum,
        runoff=runoff_sum,
        runoff_cn=runoff_cn_sum,
        soil_storage_change=soil_storage_change,
        transit_storage_change=transit_storage_change,
        cn_storage_change=cn_storage_change,
        lag_storage_change=lag_storage_change,
        residual=residual_sum,
        weights=weights,
    )
