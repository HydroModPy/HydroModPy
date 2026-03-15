"""Shared helpers to resolve flow time-dependent forcings against simulation time."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from hydromodpy.forcing.time_alignment import (
    align_forcing_series_to_simulation_window,
)
from hydromodpy.simulation.time import (
    ResolvedSimulationTimeWindow,
    build_simulation_time_boundaries,
)


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
                raise ValueError(f"{label}: no value available at simulation period starting {left}.")
            values.append(float(history.iloc[-1]))
        return values
    raise ValueError(f"{label}: unsupported aggregate mode '{aggregate}'.")


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

    mode = getattr(forcing, "mode", None)
    if mode == "constant":
        return [float(forcing.as_constant().value)] * int(nper)

    if simulation_window is None:
        raise ValueError(
            f"{label}: simulation.time is required to resolve non-constant forcing."
        )

    if mode == "csv":
        csv_cfg = forcing.as_csv()
        series = load_forcing_csv_series(
            path_file=csv_cfg.path_file,
            sep=csv_cfg.sep,
            date_column=csv_cfg.date_column,
            date_format=csv_cfg.date_format,
            value_column=csv_cfg.value_column,
            label=label,
        )
        values = aggregate_forcing_series(
            series,
            simulation_window=simulation_window,
            label=label,
            aggregate=csv_cfg.aggregate,
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

    raise ValueError(f"{label}: unsupported forcing mode '{mode}'.")
