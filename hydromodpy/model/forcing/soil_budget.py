"""The printed water-budget block of the soil reservoir (spec section 5.2)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from hydromodpy.model.contracts import LoadResultProto
from hydromodpy.model.forcing.soil_config import SeasonalKc
from hydromodpy.model.forcing.soil_forcing import SoilForcings
from hydromodpy.model.forcing.soil_ru_budget import RuClosure
from hydromodpy.model.soil.kernel import annual_budget
from hydromodpy.model.soil.laws import SOIL_METHODS


def gauged_mm_per_day(
    hydrometry: LoadResultProto | None, *, days: np.ndarray, catchment_area_km2: float | None
) -> tuple[np.ndarray, str] | str:
    """The gauged discharge over the catchment, mm/day on ``days`` (NaN without a value).

    Returns the series and the station id, or a sentence that says why there is none.
    """
    if hydrometry is None or not hydrometry.has_points:
        return "no [data.hydrometry] loaded"
    if len(hydrometry.points) != 1:
        return (
            f"{len(hydrometry.points)} stations loaded and the comparison needs the one "
            "at the outlet"
        )
    if not catchment_area_km2 or catchment_area_km2 <= 0:
        return "the catchment area is unknown"
    station = hydrometry.points[0]
    series = station.data.set_index("datetime")["value"]
    stamps = pd.DatetimeIndex(series.index)
    if stamps.tz is not None:
        stamps = stamps.tz_localize(None)
    series = series.groupby(stamps.normalize()).mean()
    daily = series.reindex(pd.DatetimeIndex(days)).to_numpy(dtype=np.float64)
    return daily * 86400 / (catchment_area_km2 * 1e6) * 1000, str(station.station_id)


def gauged_discharge_line(
    hydrometry: LoadResultProto | None, *, days: np.ndarray, catchment_area_km2: float | None
) -> str:
    """The gauged-discharge line of the printed budget, or why it is not shown."""
    gauged = gauged_mm_per_day(hydrometry, days=days, catchment_area_km2=catchment_area_km2)
    if isinstance(gauged, str):
        return f"gauged discharge: not shown, {gauged}"
    values, station_id = gauged
    start, end = pd.Timestamp(days[0]), pd.Timestamp(days[-1])
    finite = np.isfinite(values)
    if not finite.any():
        return (
            "gauged discharge: not shown, the station has no value between "
            f"{start:%Y-%m-%d} and {end:%Y-%m-%d}"
        )
    v_mm_per_year = _no_negative_zero(float(values[finite].mean()) * 365.25, 1)
    return (
        f"gauged discharge {station_id}: {v_mm_per_year:.1f} mm/year on "
        f"{int(finite.sum())} of {days.size} days, catchment {catchment_area_km2:.2f} km2"
    )


def ru_closure_lines(closure: RuClosure | None) -> tuple[str, ...]:
    """The lines that give the ru closing the budget against the gauge."""
    if closure is None:
        return ()
    if closure.ru_mm is None:
        return (f"ru closing the budget: not found, {closure.reason}",)

    def mm(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.0f}"

    band = (
        f"{closure.band_mm[0]:.0f} to {closure.band_mm[1]:.0f} mm"
        if closure.band_mm is not None
        else "n/a"
    )
    lines = [
        f"ru closing recharge + runoff against the gauge over {closure.years} years: "
        f"{closure.ru_mm:.0f} mm, {band} over resampled years (5-95 %)",
        f"  with rain -5 % / +5 %: {mm(closure.rain_minus_5_mm)} / {mm(closure.rain_plus_5_mm)} mm,"
        f" with gauge -5 % / +5 %: {mm(closure.gauge_minus_5_mm)} / "
        f"{mm(closure.gauge_plus_5_mm)} mm",
    ]
    if closure.per_10_mm_evaporation_mm is not None:
        lines.append(
            "  each 10 mm/year the water table evaporates moves it by "
            f"{closure.per_10_mm_evaporation_mm:+.0f} mm; it is an effective capacity, "
            "write it as ru and calibrate K and Sy with it fixed"
        )
    return tuple(lines)


def _no_negative_zero(value: float, decimals: int) -> float:
    """Round to ``decimals`` places without ever landing on a printed ``-0.0``.

    A sum that is really zero can carry a tiny negative float error; rounded
    and printed as is, it would read as a small deficit instead of closing.
    """
    return round(value, decimals) + 0.0


def _header_line(days: np.ndarray, n_cells: int, n_classes: int, *, has_raster: bool) -> str:
    start, end = pd.Timestamp(days[0]), pd.Timestamp(days[-1])
    if has_raster:
        classes_phrase = f"up to {n_classes} capacity classes each"
    else:
        unit = "class" if n_classes == 1 else "classes"
        classes_phrase = f"{n_classes} capacity {unit} each"
    return (
        f"Soil reservoir, {start:%Y-%m-%d} to {end:%Y-%m-%d} ({len(days)} days), "
        f"{n_cells} SAFRAN cells, {classes_phrase}"
    )


def map_mean(forcings: SoilForcings, name: str) -> float | None:
    """Basin mean of the soil map ``name`` (a key of ``SOIL_MAPS``), None without a map."""
    values = getattr(forcings.columns, name)
    if values is None:
        return None
    return float(np.sum(values * forcings.columns.basin_weight))


def _parameters_line(forcings: SoilForcings) -> str:
    config = forcings.config
    raster_mean_mm = forcings.columns.raster_mean_mm
    impervious_mean = map_mean(forcings, "impervious")
    curve_number_mean = map_mean(forcings, "curve_number")
    ratio_mean = map_mean(forcings, "infiltration_ratio")
    curve_number = config.curve_number if curve_number_mean is None else curve_number_mean
    ru_clause = (
        f"ru {config.ru:g} mm (raster mean {raster_mean_mm:.0f} mm rescaled)"
        if raster_mean_mm is not None
        else f"ru {config.ru:g} mm"
    )
    lag_clause = f", runoff lag {config.runoff_lag:g} days" if config.runoff_lag != 0.0 else ""
    cn_map = "" if curve_number_mean is None else " (basin mean of [data.curve_number])"
    cn_clause = (
        f", curve number {curve_number:.3g}{cn_map}, runoff time {config.runoff_time:g} days"
        f"{lag_clause}"
        if curve_number is not None
        else ""
    )
    impervious_clause = (
        f"impervious {100 * config.impervious_fraction:.3g} %"
        if impervious_mean is None
        else f"impervious {100 * impervious_mean:.3g} % (basin mean of [data.impervious])"
    )
    ratio = config.infiltration_ratio if ratio_mean is None else ratio_mean
    ratio_clause = (
        ""
        if ratio_mean is None and config.infiltration_ratio == 1.0
        else f", infiltration ratio {ratio:.3g}"
        + ("" if ratio_mean is None else " (basin mean of [data.infiltration_ratio])")
    )
    alpha_clause = f", alpha {config.alpha:g}" if SOIL_METHODS[config.method].reads_alpha else ""
    kc = config.kc
    kc_clause = (
        f"kc {kc.low:g} to {kc.high:g} over months {'-'.join(str(m) for m in kc.months)}"
        if isinstance(kc, SeasonalKc)
        else f"kc {kc:.4g}"
    )
    snow = config.snow
    snow_clause = (
        f", snow melting from {snow.melt_start:g} to {snow.melt_full:g} degC"
        if snow is not None
        else ""
    )
    return (
        f"method {config.method}, {ru_clause}{alpha_clause}, {kc_clause}{snow_clause}, "
        f"{impervious_clause}, "
        f"bypass {100 * config.bypass_fraction:.3g} %, "
        f"transit time {config.transit_time:g} days{cn_clause}{ratio_clause}"
    )


def _starting_soil_line(forcings: SoilForcings) -> str:
    config = forcings.config
    if config.spinup == "none":
        return 'starting soil: full (spinup = "none")'
    first_day = pd.Timestamp(forcings.days[0])
    label = (
        str(first_day.year) if (first_day.month, first_day.day) == (1, 1) else "the first 365 days"
    )
    line = f"starting soil: {label} repeated {forcings.spinup_cycles} times, settled within 0.1 mm"
    if forcings.never_full_columns > 0:
        n_columns = forcings.columns.cell_index.size
        line += f"; the soil never filled on {forcings.never_full_columns} of {n_columns} columns"
    return line


def _table_header(y_dry: int | None, y_wet: int | None) -> str:
    if y_dry is None:
        return f"{'mm/year':<22}{'mean':>8}"
    return (
        f"{'mm/year':<22}{'mean':>8}{str(y_dry) + ' least rain':>18}{str(y_wet) + ' most rain':>17}"
    )


def _data_row(
    label: str,
    array_yn: np.ndarray,
    weights: np.ndarray,
    scale: float,
    dry_idx: int | None,
    wet_idx: int | None,
    *,
    signed: bool = False,
) -> str:
    basin = array_yn @ weights
    mean = _no_negative_zero(basin.sum() / scale, 1)
    mean_str = f"{mean:>+8.1f}" if signed else f"{mean:>8.1f}"
    if dry_idx is None:
        return f"{label:<22}{mean_str}"
    dry = _no_negative_zero(basin[dry_idx], 1)
    wet = _no_negative_zero(basin[wet_idx], 1)
    dry_str = f"{dry:>+18.1f}" if signed else f"{dry:>18.1f}"
    wet_str = f"{wet:>+17.1f}" if signed else f"{wet:>17.1f}"
    return f"{label:<22}{mean_str}{dry_str}{wet_str}"


def _summer_line(forcings: SoilForcings) -> str | None:
    months = pd.DatetimeIndex(forcings.days).month
    summer = np.isin(months, (7, 8, 9))
    if not summer.any():
        return None
    basin_recharge = forcings.fluxes.recharge @ forcings.columns.basin_weight
    value = _no_negative_zero(float(np.mean(basin_recharge[summer])), 3)
    return f"recharge July-September: {value:.3f} mm/day"


def soil_budget_lines(
    forcings: SoilForcings,
    *,
    ladder: tuple[tuple[float, float], ...],
    gauged_line: str,
    sent_to_evt: bool,
    closure: RuClosure | None = None,
) -> tuple[str, ...]:
    """The printed soil water-budget block of spec section 5.2, one str per line."""
    days = forcings.days
    n_days = len(days)
    n_cells = int(np.unique(forcings.columns.cell_index).size)
    n_classes = int(forcings.columns.class_index.max()) + 1
    raster_mean_mm = forcings.columns.raster_mean_mm

    annual = annual_budget(
        forcings.years,
        forcings.precipitation,
        forcings.etp,
        forcings.fluxes,
        forcings.columns.basin_weight,
    )
    full_years = annual.days >= 365
    if np.any(full_years):
        precipitation_totals = np.where(full_years, annual.basin("precipitation"), np.nan)
        dry_idx = int(np.nanargmin(precipitation_totals))
        wet_idx = int(np.nanargmax(precipitation_totals))
        y_dry, y_wet = int(annual.years[dry_idx]), int(annual.years[wet_idx])
    else:
        dry_idx = wet_idx = y_dry = y_wet = None

    scale = n_days / 365.25
    storage_change = (
        annual.soil_storage_change
        + annual.transit_storage_change
        + annual.cn_storage_change
        + annual.lag_storage_change
        + annual.snow_storage_change
    )
    quick = annual.runoff_quick if annual.runoff_quick is not None else 0.0 * annual.runoff
    impervious_only = annual.runoff - annual.runoff_cn - quick

    lines = [
        _header_line(days, n_cells, n_classes, has_raster=raster_mean_mm is not None),
        _parameters_line(forcings),
        _starting_soil_line(forcings),
        _table_header(y_dry, y_wet),
        _data_row("precipitation", annual.precipitation, annual.weights, scale, dry_idx, wet_idx),
        _data_row("ETP", annual.etp, annual.weights, scale, dry_idx, wet_idx),
        _data_row("ETR", annual.etr, annual.weights, scale, dry_idx, wet_idx),
        _data_row("recharge to MODFLOW", annual.recharge, annual.weights, scale, dry_idx, wet_idx),
        _data_row("impervious runoff", impervious_only, annual.weights, scale, dry_idx, wet_idx),
    ]
    if forcings.parameters.curve_number is not None:
        lines.append(
            _data_row(
                "curve-number runoff", annual.runoff_cn, annual.weights, scale, dry_idx, wet_idx
            )
        )
    if np.any(np.asarray(forcings.parameters.infiltration_ratio) != 1.0):
        lines.append(
            _data_row("quick runoff (1 - ratio)", quick, annual.weights, scale, dry_idx, wet_idx)
        )
    lines.extend(
        [
            _data_row(
                "storage change",
                storage_change,
                annual.weights,
                scale,
                dry_idx,
                wet_idx,
                signed=True,
            ),
            _data_row("closure", annual.residual, annual.weights, scale, dry_idx, wet_idx),
        ]
    )

    unmet = _no_negative_zero(float((annual.residual_etp @ annual.weights).sum() / scale), 1)
    if sent_to_evt:
        lines.append(
            f"unmet ETP {unmet:.1f} mm/year, offered to EVT: the water table gives "
            "it only where it is shallow"
        )
    else:
        lines.append(
            f'unmet ETP {unmet:.1f} mm/year, not sent to MODFLOW: add "etp" to '
            "[flow.sinks_sources.etp] to let a shallow water table evaporate it"
        )

    summer_line = _summer_line(forcings)
    if summer_line is not None:
        lines.append(summer_line)

    ladder_text = " | ".join(f"{ru:g} mm {_no_negative_zero(v, 1):.1f}" for ru, v in ladder)
    lines.append(f"recharge for other ru, mm/year: {ladder_text}")

    lines.append(gauged_line)
    lines.extend(ru_closure_lines(closure))

    return tuple(lines)
