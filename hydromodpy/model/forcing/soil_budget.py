"""The printed water-budget block of the soil reservoir (spec section 5.2)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from hydromodpy.model.contracts import LoadResultProto
from hydromodpy.model.forcing.soil_config import SoilReservoirConfig
from hydromodpy.model.forcing.soil_forcing import SoilForcings
from hydromodpy.model.soil.kernel import annual_budget


def gauged_discharge_line(
    hydrometry: LoadResultProto | None, *, days: np.ndarray, catchment_area_km2: float | None
) -> str:
    """The gauged-discharge line of the printed budget, or why it is not shown."""
    if hydrometry is None or not hydrometry.has_points:
        return "gauged discharge: not shown, no [data.hydrometry] loaded"
    if len(hydrometry.points) != 1:
        return (
            f"gauged discharge: not shown, {len(hydrometry.points)} stations loaded "
            "and the comparison needs the one at the outlet"
        )
    if not catchment_area_km2 or catchment_area_km2 <= 0:
        return "gauged discharge: not shown, the catchment area is unknown"

    start, end = pd.Timestamp(days[0]), pd.Timestamp(days[-1])
    station = hydrometry.points[0]
    series = station.data.set_index("datetime")["value"]
    windowed = series[(series.index >= start) & (series.index <= end)].dropna()
    if windowed.empty:
        return (
            "gauged discharge: not shown, the station has no value between "
            f"{start:%Y-%m-%d} and {end:%Y-%m-%d}"
        )

    mean_q_m3s = float(windowed.mean())
    v_mm_per_year = _no_negative_zero(
        mean_q_m3s * 86400 * 365.25 / (catchment_area_km2 * 1e6) * 1000, 1
    )
    return (
        f"gauged discharge {station.station_id}: {v_mm_per_year:.1f} mm/year on "
        f"{windowed.size} of {days.size} days, catchment {catchment_area_km2:.2f} km2"
    )


# ---------------------------------------------------------------------------
# Printed water-budget block (spec section 5.2)
# ---------------------------------------------------------------------------


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


def _parameters_line(config: SoilReservoirConfig, raster_mean_mm: float | None) -> str:
    ru_clause = (
        f"ru {config.ru:g} mm (raster mean {raster_mean_mm:.0f} mm rescaled)"
        if raster_mean_mm is not None
        else f"ru {config.ru:g} mm"
    )
    lag_clause = f", runoff lag {config.runoff_lag:g} days" if config.runoff_lag != 0.0 else ""
    cn_clause = (
        f", curve number {config.curve_number:g}, runoff time {config.runoff_time:g} days"
        f"{lag_clause}"
        if config.curve_number is not None
        else ""
    )
    return (
        f"{ru_clause}, alpha {config.alpha:g}, kc {config.kc:.4g}, "
        f"impervious {100 * config.impervious_fraction:.3g} %, "
        f"bypass {100 * config.bypass_fraction:.3g} %, "
        f"transit time {config.transit_time:g} days{cn_clause}"
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
    )
    impervious_only = annual.runoff - annual.runoff_cn

    lines = [
        _header_line(days, n_cells, n_classes, has_raster=raster_mean_mm is not None),
        _parameters_line(forcings.config, raster_mean_mm),
        _starting_soil_line(forcings),
        _table_header(y_dry, y_wet),
        _data_row("precipitation", annual.precipitation, annual.weights, scale, dry_idx, wet_idx),
        _data_row("ETP", annual.etp, annual.weights, scale, dry_idx, wet_idx),
        _data_row("ETR", annual.etr, annual.weights, scale, dry_idx, wet_idx),
        _data_row("recharge to MODFLOW", annual.recharge, annual.weights, scale, dry_idx, wet_idx),
        _data_row("impervious runoff", impervious_only, annual.weights, scale, dry_idx, wet_idx),
    ]
    if forcings.config.curve_number is not None:
        lines.append(
            _data_row(
                "curve-number runoff", annual.runoff_cn, annual.weights, scale, dry_idx, wet_idx
            )
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

    return tuple(lines)
