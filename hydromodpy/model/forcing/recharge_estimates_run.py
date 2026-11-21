"""Run the ``[recharge_estimates]`` methods on the loaded data and lay out their rows.

The weather is reduced to one basin series (the mean of the grid cells, or of
the stations), the gauge is turned into mm/day over the catchment area, and
each piezometer gives its own estimate. A method whose data is missing is
skipped with a sentence that says why, and the run goes on: these numbers are
a comparison, the model never reads them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

import numpy as np
import pandas as pd

from hydromodpy.core.units.quantities import SECONDS_PER_DAY
from hydromodpy.model.contracts import LoadResultProto
from hydromodpy.model.forcing.cells import spatial_mean_from_fields
from hydromodpy.model.forcing.forcing_bridge import extract_homogeneous_series
from hydromodpy.model.forcing.recharge_estimates import (
    GAP_DAYS_DISCHARGE,
    GAP_DAYS_HEAD,
    annual_totals,
    chapman_maxwell,
    daily_pieces,
    eckhardt,
    guttman_zuckerman,
    kessler,
    recession_constant,
    turc,
    wallingford,
    wtf,
)
from hydromodpy.model.forcing.recharge_estimates_config import RechargeEstimatesConfig
from hydromodpy.model.forcing.recharge_estimators import ESTIMATORS, WEATHER_ESTIMATORS
from hydromodpy.model.forcing.soil_forcing import SoilForcings, basin_water_out

Water = tuple[pd.Series, pd.Series]
"""A daily basin recharge and runoff, mm/day, on the same days."""


def basin_series(result: LoadResultProto | None) -> pd.Series | None:
    """One daily series for the basin: the mean of the grid cells, else of the stations."""
    if result is None:
        return None
    series = spatial_mean_from_fields(result) if result.has_fields else None
    if series is None and result.has_points:
        series = extract_homogeneous_series(result)
    if series is None or series.empty:
        return None
    series.index = pd.DatetimeIndex(series.index).tz_localize(None).normalize()
    return series.groupby(level=0).mean()


def gauge_mm_per_day(hydrometry: LoadResultProto | None, area_km2: float | None) -> pd.Series | str:
    """The outlet discharge in mm/day over the catchment, or why there is none."""
    if hydrometry is None or not hydrometry.has_points:
        return "no [data.hydrometry] loaded"
    if len(hydrometry.points) != 1:
        return (
            f"{len(hydrometry.points)} gauges loaded, and the estimate reads the one at the outlet"
        )
    if not area_km2 or area_km2 <= 0:
        return "the catchment area is unknown"
    data = hydrometry.points[0].data
    series = data.set_index("datetime")["value"].astype(np.float64)
    series.index = pd.DatetimeIndex(series.index).tz_localize(None).normalize()
    return series.groupby(level=0).mean() * SECONDS_PER_DAY / (area_km2 * 1e6) * 1000.0


def _naive(instant) -> pd.Timestamp:
    """``instant`` as a timestamp without time zone, the convention of the series here."""
    stamp = pd.Timestamp(instant)
    return stamp.tz_localize(None) if stamp.tz is not None else stamp


def _row(
    method: str,
    year: int | None,
    quantity: str,
    value: float,
    unit: str = "mm",
    station=None,
    month: int | None = None,
):
    return {
        "method": method,
        "station": station,
        "year": year,
        "month": month,
        "quantity": quantity,
        "value": float(value),
        "unit": unit,
    }


def water_balance_rows(
    rain_minus_etr: pd.Series, gauge: pd.Series | str
) -> tuple[list[dict], list[str]]:
    """Monthly rain minus ETR beside the gauged discharge, mm per month.

    Abherve (2022, section 2.2.3) reads the loop the two draw over the year:
    above the line ``P - E = Q/A`` the catchment stores water, below it the
    aquifer drains. A month counts when the gauge covers 90 % of its days.
    """
    if isinstance(gauge, str):
        return [], [f"water_balance: {gauge}"]
    common = rain_minus_etr.index.intersection(gauge.dropna().index)
    if common.size < 365:
        return [], ["water_balance: the gauge and the soil share less than a year"]
    frame = pd.DataFrame({"pe": rain_minus_etr[common], "q": gauge[common]})
    month_start = frame.index.to_period("M")
    counts = frame.groupby(month_start).size()
    sums = frame.groupby(month_start).sum()
    rows = []
    for period, total in sums.iterrows():
        if counts[period] < 0.9 * period.days_in_month:
            continue
        for quantity, value in (("rain_minus_etr", total["pe"]), ("gauged_discharge", total["q"])):
            rows.append(_row("water_balance", period.year, quantity, value, month=period.month))
    return rows, []


def weather_estimate(
    name: str, precipitation: pd.Series | None, temperature: pd.Series | None
) -> pd.Series | str:
    """The yearly values, mm, of the weather formula ``name``, or why there are none.

    ``precipitation`` and ``temperature`` are daily basin series. A year counts
    when it is covered on 90 % of its days; Kessler also needs the year before.
    """
    if precipitation is None:
        return "no precipitation loaded"
    rain = annual_totals(precipitation)
    if name == "guttman_zuckerman":
        return pd.Series(guttman_zuckerman(rain.to_numpy()), index=rain.index)
    if name == "turc":
        if temperature is None:
            return "no temperature loaded"
        mean_t = temperature.groupby(temperature.index.year).mean().reindex(rain.index)
        return pd.Series(turc(rain.to_numpy(), mean_t.to_numpy()), index=rain.index).dropna()
    years = rain.index.to_numpy()
    month = precipitation.index.month
    by_year = precipitation.index.year
    # Kessler reads shares of the year, so the year and its months are sums of
    # the same days, not the year scaled to a full year.
    whole = precipitation.groupby(by_year).sum().reindex(years)
    spring = precipitation[month <= 4].groupby(by_year[month <= 4]).sum().reindex(years)
    autumn = precipitation[month >= 9].groupby(by_year[month >= 9]).sum().reindex(years)
    consecutive = np.all(np.diff(years) == 1) if years.size > 1 else False
    if years.size < 2 or not consecutive:
        return "needs two consecutive complete years of precipitation"
    values = kessler(whole.to_numpy(), spring.to_numpy(), autumn.to_numpy())
    return pd.Series(values, index=rain.index).dropna()


def _weather_rows(
    selected: tuple[str, ...], precipitation: pd.Series | None, temperature: pd.Series | None
) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    notes: list[str] = []
    for name in (n for n in WEATHER_ESTIMATORS if n in selected):
        yearly = weather_estimate(name, precipitation, temperature)
        if isinstance(yearly, str):
            notes.append(f"{name}: {yearly}")
            continue
        quantity = ESTIMATORS[name].gives
        rows += [_row(name, int(year), quantity, value) for year, value in yearly.items()]
    return rows, notes


def _gauge_rows(
    selected: tuple[str, ...], config: RechargeEstimatesConfig, gauge: pd.Series | str
) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    wants = [n for n in ("wallingford", "chapman_maxwell", "eckhardt") if n in selected]
    if not wants:
        return rows, []
    if isinstance(gauge, str):
        return rows, [f"{name}: {gauge}" for name in wants]
    pieces = daily_pieces(gauge, GAP_DAYS_DISCHARGE)
    if not pieces:
        return rows, [f"{name}: the gauge holds no stretch of 10 days" for name in wants]

    wall = pd.concat([pd.Series(wallingford(p.to_numpy()), index=p.index) for p in pieces])
    flow = pd.concat(pieces)
    wall_years = annual_totals(wall)
    flow_years = flow[wall.notna()].groupby(flow[wall.notna()].index.year).sum()
    base_years = wall.dropna().groupby(wall.dropna().index.year).sum()
    bfi = (base_years / flow_years).reindex(wall_years.index)
    if "wallingford" in wants:
        for year, value in wall_years.items():
            rows.append(_row("wallingford", int(year), "recharge", value))
            rows.append(_row("wallingford", int(year), "baseflow_index", bfi[year], unit="-"))

    notes: list[str] = []
    k_read = [recession_constant(p.to_numpy()) for p in pieces]
    k_read = [k for k in k_read if np.isfinite(k)]
    gauge_k = float(np.mean(k_read)) if k_read else float("nan")
    for name in ("chapman_maxwell", "eckhardt"):
        if name not in wants:
            continue
        options = getattr(config, name)
        k = options.k if options.k is not None else gauge_k
        if not np.isfinite(k):
            notes.append(f"{name}: no recession of 5 days on the gauge to read k from")
            continue
        if name == "eckhardt":
            bfi_max = options.bfi_max
            if bfi_max is None:
                finite = bfi.dropna()
                if finite.empty:
                    notes.append("eckhardt: no Wallingford index to take BFImax from")
                    continue
                bfi_max = round(float(finite.max()), 2)
            series = pd.concat(
                [pd.Series(eckhardt(p.to_numpy(), k, bfi_max), index=p.index) for p in pieces]
            )
            rows.append(_row(name, None, "recession_constant", k, unit="-"))
            rows.append(_row(name, None, "bfi_max", bfi_max, unit="-"))
        else:
            series = pd.concat(
                [pd.Series(chapman_maxwell(p.to_numpy(), k), index=p.index) for p in pieces]
            )
            rows.append(_row(name, None, "recession_constant", k, unit="-"))
        for year, value in annual_totals(series).items():
            rows.append(_row(name, int(year), "recharge", value))
    return rows, notes


def _wtf_rows(
    config: RechargeEstimatesConfig, piezometry: LoadResultProto | None, cut
) -> tuple[list[dict], list[str]]:
    if piezometry is None or not piezometry.has_points:
        return [], ["wtf: no [data.piezometry] loaded"]
    rows: list[dict] = []
    notes: list[str] = []
    for record in piezometry.points:
        head = record.data.set_index("datetime")["value"].astype(np.float64)
        stamps = pd.DatetimeIndex(head.index)
        head.index = stamps.tz_localize(None) if stamps.tz is not None else stamps
        pieces = daily_pieces(cut(head), GAP_DAYS_HEAD)
        if not pieces:
            notes.append(f"wtf {record.station_id}: no stretch of 10 days without a gap")
            continue
        daily = pd.concat(
            [
                pd.Series(
                    wtf(p.to_numpy(), config.wtf.specific_yield, correction=config.wtf.correction),
                    index=p.index,
                )
                for p in pieces
            ]
        )
        for year, value in annual_totals(daily).items():
            rows.append(_row("wtf", int(year), "recharge", value, station=str(record.station_id)))
    return rows, notes


def soil_law_water(soil: SoilForcings, laws: tuple[str, ...]) -> tuple[dict[str, Water], list[str]]:
    """The daily basin recharge and runoff of each soil law on the forcing of ``soil``.

    Every law reads the same rain, ETP, ru, crop coefficient, snow and sealed
    share; only the storage law changes. A law whose soil never settles in its
    spin-up is left out with a sentence.
    """
    index = pd.DatetimeIndex(soil.days)
    water: dict[str, Water] = {}
    notes: list[str] = []
    for law in laws:
        # model_copy, not model_validate: alpha stays written for a law that does not
        # read it, and the kernel leaves it unread.
        forcings = replace(soil, config=soil.config.model_copy(update={"method": law}))
        out = basin_water_out(forcings, float(soil.config.ru))
        if out is None:
            notes.append(f"{law}: its soil does not settle within 20 spin-up cycles")
            continue
        water[law] = (pd.Series(out[0], index=index), pd.Series(out[1], index=index))
    return water, notes


def monthly_sums(daily: pd.Series) -> pd.Series:
    """Sum of a daily series per month, for months covered on 90 % of their days."""
    daily = daily.dropna()
    if daily.empty:
        return pd.Series(dtype=np.float64)
    month = daily.index.to_period("M")
    counts = daily.groupby(month).size()
    sums = daily.groupby(month).sum()
    days = pd.Series([period.days_in_month for period in counts.index], index=counts.index)
    return sums[counts >= 0.9 * days]


def signal_rows(
    compared: Mapping[str, Water],
    run_water: Water | None,
    precipitation: pd.Series | None,
    etp: pd.Series | None,
) -> list[dict]:
    """Monthly recharge and runoff of each method and of the run, beside the weather.

    Each compared method also gets yearly recharge rows, so it sits in the range
    of the yearly estimators. Its runoff stays monthly: a yearly runoff row would
    be read as a recharge by the readers that group the yearly rows by method.
    """
    rows: list[dict] = []
    for method, water in compared.items():
        rows += [_row(method, int(y), "recharge", v) for y, v in annual_totals(water[0]).items()]
    for method, water in (*compared.items(), *((("run", run_water),) if run_water else ())):
        for quantity, daily in zip(("recharge", "runoff"), water, strict=True):
            for period, value in monthly_sums(daily).items():
                rows.append(_row(method, period.year, quantity, value, month=period.month))
    for quantity, daily in (("precipitation", precipitation), ("etp", etp)):
        if daily is not None:
            for period, value in monthly_sums(daily).items():
                rows.append(_row("input", period.year, quantity, value, month=period.month))
    return rows


def estimate_recharge(
    config: RechargeEstimatesConfig,
    *,
    precipitation: LoadResultProto | None,
    temperature: LoadResultProto | None,
    hydrometry: LoadResultProto | None,
    piezometry: LoadResultProto | None,
    area_km2: float | None,
    run_water: tuple[pd.Series, pd.Series] | None,
    rain_minus_etr: pd.Series | None = None,
    window: tuple[pd.Timestamp, pd.Timestamp] | None = None,
    etp: LoadResultProto | None = None,
    compared: Mapping[str, Water] | None = None,
) -> tuple[list[dict], list[str]]:
    """The rows of ``recharge_estimates`` and the sentences for the methods skipped.

    ``run_water`` is the run's own daily basin recharge and runoff, mm/day,
    when the run computes or loads them. Its recharge is written as the method
    ``run``, and with the gauge it gives the closing factor. ``rain_minus_etr``,
    the daily basin rain minus the soil's ETR, gives the monthly ``water_balance``
    rows the hysteresis figure draws. ``window`` is the run's ``(start, end)``:
    every series is cut to it, so all methods read the same years. ``compared``
    holds the daily water of each soil law and loaded product to set beside the
    run; with it, or when the section asks for signals, the monthly rows of
    recharge, runoff, rain and ETP are written too.
    """

    def cut(series):
        if series is None or isinstance(series, str) or window is None:
            return series
        start, end = (_naive(t) for t in window)
        return series[(series.index >= start.normalize()) & (series.index <= end)]

    selected = config.selected()
    rows, notes = _weather_rows(
        selected, cut(basin_series(precipitation)), cut(basin_series(temperature))
    )
    gauge = cut(gauge_mm_per_day(hydrometry, area_km2))
    more, more_notes = _gauge_rows(selected, config, gauge)
    rows += more
    notes += more_notes
    if "wtf" in selected:
        more, more_notes = _wtf_rows(config, piezometry, cut)
        rows += more
        notes += more_notes
    if run_water is not None:
        for year, value in annual_totals(run_water[0]).items():
            rows.append(_row("run", int(year), "recharge", value))
    if rain_minus_etr is not None:
        more, more_notes = water_balance_rows(rain_minus_etr, gauge)
        rows += more
        notes += more_notes
    if config.signals():
        cut_water = {name: (cut(r), cut(q)) for name, (r, q) in (compared or {}).items()}
        run_cut = None if run_water is None else (cut(run_water[0]), cut(run_water[1]))
        rows += signal_rows(
            cut_water, run_cut, cut(basin_series(precipitation)), cut(basin_series(etp))
        )
    if "closing_factor" in selected:
        if isinstance(gauge, str):
            notes.append(f"closing_factor: {gauge}")
        elif run_water is None:
            notes.append("closing_factor: the run has no daily recharge and runoff to scale")
        else:
            water = (run_water[0] + run_water[1]).dropna()
            common = water.index.intersection(gauge.dropna().index)
            if common.size < 365:
                notes.append("closing_factor: the gauge and the run share less than a year")
            else:
                factor = gauge[common].mean() / water[common].mean()
                rows.append(_row("closing_factor", None, "factor", factor, unit="-"))
    return rows, notes


def estimate_lines(rows: list[dict], notes: list[str]) -> tuple[str, ...]:
    """The printed block: one line per method, its mean, range and years."""
    lines = ["Recharge estimated from the data, mm/year (compared with the run, never read by it)"]
    frame = pd.DataFrame(rows)
    if not frame.empty:
        yearly = frame[frame["year"].notna() & (frame["unit"] == "mm") & frame["month"].isna()]
        for (method, station), group in yearly.groupby(["method", "station"], dropna=False):
            label = method if station is None or pd.isna(station) else f"{method} {station}"
            quantity = group["quantity"].iloc[0].replace("_", " ")
            values = group["value"]
            lines.append(
                f"  {label:<28}{values.mean():>8.0f}  ({values.min():.0f} to {values.max():.0f}, "
                f"{len(values)} years, {quantity})"
            )
        monthly = frame[frame["month"].notna() & (frame["quantity"] == "runoff")]
        if not monthly.empty:
            per_year = monthly.groupby("method", sort=False)["value"].agg(["sum", "size"])
            parts = [
                f"{method} {row['sum'] * 12.0 / row['size']:.0f}"
                for method, row in per_year.iterrows()
            ]
            lines.append(f"  runoff of the same, mm/year: {', '.join(parts)}")
        factor = frame[frame["method"] == "closing_factor"]
        if not factor.empty:
            lines.append(
                f"  closing factor {factor['value'].iloc[0]:.3f}: the run's recharge and runoff "
                "times this number match the gauged volume"
            )
    lines.extend(f"  skipped {note}" for note in notes)
    return tuple(lines)


def soil_rain_minus_etr(soil: object | None) -> pd.Series | None:
    """The daily basin rain minus the soil's ETR, mm/day, or None without a soil."""
    if soil is None:
        return None
    weights = soil.columns.basin_weight
    index = pd.DatetimeIndex(soil.days)
    return pd.Series(soil.precipitation @ weights - soil.fluxes.etr @ weights, index=index)


def run_water_series(
    soil: object | None, recharge: LoadResultProto | None, runoff: LoadResultProto | None
) -> tuple[pd.Series, pd.Series] | None:
    """The run's daily basin recharge and runoff, mm/day, from the soil or the loaded series."""
    if soil is not None:
        weights = soil.columns.basin_weight
        index = pd.DatetimeIndex(soil.days)
        return (
            pd.Series(soil.fluxes.recharge @ weights, index=index),
            pd.Series(soil.fluxes.runoff @ weights, index=index),
        )
    loaded = basin_series(recharge)
    if loaded is None:
        return None
    surface = basin_series(runoff)
    if surface is None:
        surface = pd.Series(0.0, index=loaded.index)
    return loaded, surface.reindex(loaded.index).fillna(0.0)


__all__ = [
    "basin_series",
    "estimate_lines",
    "estimate_recharge",
    "gauge_mm_per_day",
    "monthly_sums",
    "signal_rows",
    "soil_law_water",
    "run_water_series",
    "soil_rain_minus_etr",
    "water_balance_rows",
    "weather_estimate",
]
