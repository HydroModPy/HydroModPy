"""Shared helpers to resolve flow time-dependent forcings against simulation time."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pandas as pd

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.time import (
    ResolvedSimulationTimeWindow,
    build_simulation_time_boundaries,
)
from hydromodpy.physics.forcing.time_alignment import (
    align_forcing_series_to_simulation_window,
)

if TYPE_CHECKING:
    from hydromodpy.physics.flow.sinks_sources.wells import (
        FlowWellForcingPiecewiseConfig,
        FlowWellForcingSeasonalConfig,
    )

_SEASON_BY_MONTH = {
    12: "DJF",
    1: "DJF",
    2: "DJF",
    3: "MAM",
    4: "MAM",
    5: "MAM",
    6: "JJA",
    7: "JJA",
    8: "JJA",
    9: "SON",
    10: "SON",
    11: "SON",
}


def load_forcing_csv_series(
    *,
    path_file: Path,
    sep: str,
    date_column: str,
    date_format: str | None,
    value_column: str,
    label: str,
) -> pd.Series:
    """Load one datetime-indexed forcing chronicle from CSV."""
    frame = pd.read_csv(path_file, sep=sep)
    if date_column not in frame.columns:
        raise ValueError(f"{label}: CSV column '{date_column}' is missing in {path_file}.")
    if value_column not in frame.columns:
        raise ValueError(f"{label}: CSV column '{value_column}' is missing in {path_file}.")

    dates = pd.to_datetime(frame[date_column], format=date_format)
    values = pd.to_numeric(frame[value_column], errors="coerce")
    if values.isna().any():
        raise ValueError(f"{label}: non-numeric values found in column '{value_column}'.")

    series = pd.Series(values.to_numpy(dtype=float), index=dates, dtype=float)
    series = series[~series.index.isna()]
    if series.empty:
        raise ValueError(f"{label}: CSV chronicle is empty after datetime parsing.")
    series = series.sort_index()
    if series.index.has_duplicates:
        series = series.groupby(level=0).mean()
    return series


def aggregate_forcing_series(
    series: pd.Series,
    *,
    simulation_window: ResolvedSimulationTimeWindow,
    label: str,
    aggregate: str,
) -> list[float]:
    """Aggregate one forcing chronicle to simulation stress periods."""
    aligned = align_forcing_series_to_simulation_window(
        series,
        simulation_window=simulation_window,
        label=label,
    )
    if aggregate == "mean":
        return [float(value) for value in aligned.to_list()]
    if aggregate == "last":
        boundaries = pd.DatetimeIndex(aligned.index)
        data = series.copy().sort_index()
        values: list[float] = []
        for left in boundaries:
            history = data.loc[data.index <= left]
            if history.empty:
                raise ValueError(
                    f"{label}: no value available at simulation period starting {left}."
                )
            values.append(float(history.iloc[-1]))
        return values
    raise ValueError(f"{label}: unsupported aggregate mode '{aggregate}'.")


def _forcing_attr(forcing: object, name: str) -> object:
    """Read one forcing attribute from either a config object or a mapping."""
    if isinstance(forcing, Mapping):
        return forcing.get(name)
    return getattr(forcing, name, None)


def resolve_period_values_from_forcing(
    *,
    forcing: object,
    simulation_window: ResolvedSimulationTimeWindow | None,
    nper: int,
    label: str,
) -> list[float]:
    """Resolve one forcing declaration to one value per solver period."""
    if nper <= 0:
        return []

    kind = _forcing_attr(forcing, "kind") or _forcing_attr(forcing, "mode")
    if kind == "constant":
        constant_value = _forcing_attr(forcing, "value")
        magnitude = getattr(constant_value, "magnitude", constant_value)
        return [float(magnitude)] * int(nper)

    if kind == "values":
        # Pre-resolved per-period values (e.g. a file-loaded lake forcing already
        # aligned to the simulation stress periods).
        values = _forcing_attr(forcing, "values")
        if values is None:
            raise ValueError(f"{label}: a 'values' forcing requires a values list.")
        resolved = [float(v) for v in values]
        if len(resolved) != int(nper):
            raise ValueError(
                f"{label}: pre-resolved forcing length ({len(resolved)}) does not match "
                f"nper ({int(nper)})."
            )
        return resolved

    if simulation_window is None:
        raise ValueError(f"{label}: simulation.time is required to resolve non-constant forcing.")

    if kind == "csv":
        series = load_forcing_csv_series(
            path_file=forcing.path_file,
            sep=forcing.sep,
            date_column=forcing.date_column,
            date_format=forcing.date_format,
            value_column=forcing.value_column,
            label=label,
        )
        values = aggregate_forcing_series(
            series,
            simulation_window=simulation_window,
            label=label,
            aggregate=forcing.aggregate,
        )
        expected_nper = len(build_simulation_time_boundaries(simulation_window)) - 1
        if len(values) != expected_nper:
            raise ValueError(
                f"{label}: resolved forcing length ({len(values)}) does not match "
                f"simulation window stress periods ({expected_nper})."
            )
        if expected_nper != int(nper):
            raise ValueError(
                f"{label}: resolved forcing length ({expected_nper}) does not match nper ({int(nper)})."
            )
        return values

    if kind == "piecewise":
        return _resolve_piecewise(
            forcing=cast("FlowWellForcingPiecewiseConfig", forcing),
            simulation_window=simulation_window,
            nper=nper,
            label=label,
        )

    if kind == "seasonal":
        return _resolve_seasonal(
            forcing=cast("FlowWellForcingSeasonalConfig", forcing),
            simulation_window=simulation_window,
            label=label,
        )

    raise ValueError(f"{label}: unsupported forcing kind '{kind}'.")


def _resolve_piecewise(
    *,
    forcing: FlowWellForcingPiecewiseConfig,
    simulation_window: ResolvedSimulationTimeWindow,
    nper: int,
    label: str,
) -> list[float]:
    """Resolve a piecewise forcing by selecting one dated segment per period."""
    boundaries = build_simulation_time_boundaries(simulation_window)
    period_starts = pd.DatetimeIndex(boundaries[:-1])
    window_end = boundaries[-1]
    values: list[float] = [float("nan")] * len(period_starts)
    covered = [False] * len(period_starts)
    for segment in forcing.segments:
        seg_start = pd.Timestamp(segment.start)
        seg_end = pd.Timestamp(segment.end) if segment.end is not None else window_end
        mask = (period_starts >= seg_start) & (period_starts < seg_end)
        if not bool(mask.any()):
            continue
        sub = resolve_period_values_from_forcing(
            forcing=segment.forcing,
            simulation_window=simulation_window,
            nper=nper,
            label=f"{label}.segments[{seg_start.date()}]",
        )
        for index in range(len(values)):
            if bool(mask[index]):
                values[index] = sub[index]
                covered[index] = True
    if not all(covered):
        raise ConfigError(f"{label}: piecewise segments do not cover every stress period.")
    return values


def _resolve_seasonal(
    *,
    forcing: FlowWellForcingSeasonalConfig,
    simulation_window: ResolvedSimulationTimeWindow,
    label: str,
) -> list[float]:
    """Resolve a seasonal forcing by mapping each period start to its month/season."""
    boundaries = build_simulation_time_boundaries(simulation_window)
    period_starts = pd.DatetimeIndex(boundaries[:-1])
    period_ends = pd.DatetimeIndex(boundaries[1:])
    by_month = forcing.by_month
    by_season = forcing.by_season
    out: list[float] = []
    for left, right in zip(period_starts, period_ends, strict=False):
        first_month = pd.Timestamp(year=left.year, month=left.month, day=1)
        spanned = pd.date_range(first_month, right, freq="MS", inclusive="left")
        months = spanned if len(spanned) > 0 else pd.DatetimeIndex([first_month])
        if by_month is not None:
            samples = [by_month[int(month.month)] for month in months]
        else:
            assert by_season is not None
            samples = [by_season[_SEASON_BY_MONTH[int(month.month)]] for month in months]
        out.append(sum(samples) / len(samples))
    return out
