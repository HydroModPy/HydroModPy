"""Flow-side binders for data-to-structure updates."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from hydromodpy.process.flow.sinks_sources import FlowRechargeConfig
from hydromodpy.process.flow.sinks_sources import FlowSinksSourcesConfig
from hydromodpy.simulation.forcing.recharge_chronicle import (
    align_forcing_series_to_simulation_window,
)
from hydromodpy.simulation.time import ResolvedSimulationTimeWindow
from hydromodpy.simulation.time import build_simulation_time_boundaries

if TYPE_CHECKING:
    from hydromodpy.data_managers.climatic import Climatic
    from hydromodpy.data_managers.oceanic import Oceanic
    from hydromodpy.process import Flow


def apply_oceanic_to_flow(
    *,
    flow: "Flow",
    oceanic: "Oceanic" | None,
) -> None:
    """Inject mean sea-level value into the active ocean boundary condition."""
    if oceanic is None:
        return
    ocean_bc = flow.boundary_conditions.get("ocean")
    if ocean_bc is None:
        return
    ocean_bc.value = oceanic.MSL


def apply_climatic_to_flow_recharge(
    *,
    flow: "Flow",
    climatic: "Climatic" | None,
) -> None:
    """Inject loaded climatic recharge into the flow recharge sink/source.

    This binder keeps solver-side recharge policy declared in
    ``flow.sinks_sources.recharge`` (``first_clim``, ``negative_to_evt``) and
    only replaces the ``values`` payload with runtime-loaded climatic recharge.
    """
    if climatic is None or getattr(climatic, "recharge", None) is None:
        return
    sinks_sources = getattr(flow, "sinks_sources", {})
    recharge_cfg = sinks_sources.get("recharge") if isinstance(sinks_sources, dict) else None
    if recharge_cfg is None:
        return

    flow.set_recharge(
        FlowRechargeConfig(
            values=climatic.recharge,
            first_clim=recharge_cfg.first_clim,
            units=getattr(recharge_cfg, "units", "m/s"),
            negative_to_evt=recharge_cfg.negative_to_evt,
        )
    )


def _load_well_csv_series(
    *,
    path_file: Path,
    sep: str,
    date_column: str,
    date_format: str | None,
    value_column: str,
    label: str,
) -> pd.Series:
    """Load one datetime-indexed well chronicle from CSV."""
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


def _aggregate_well_series(
    series: pd.Series,
    *,
    simulation_window: ResolvedSimulationTimeWindow,
    label: str,
    aggregate: str,
) -> list[float]:
    """Aggregate one well chronicle to simulation stress periods."""
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


def apply_simulation_time_to_flow_wells(
    *,
    flow: "Flow",
    simulation_window: ResolvedSimulationTimeWindow | None,
) -> None:
    """Resolve flow well.forcing payloads to period-aligned well.flux values."""
    if simulation_window is None:
        return

    sinks_sources = getattr(flow, "sinks_sources", {})
    wells = sinks_sources.get("wells", {}) if isinstance(sinks_sources, Mapping) else {}
    if not wells:
        return

    updated_wells: dict[str, object] = {}
    changed = False
    for well_id, well_cfg in wells.items():
        forcing = getattr(well_cfg, "forcing", None)
        if forcing is None:
            updated_wells[well_id] = well_cfg
            continue

        label = f"flow.sinks_sources.wells.{well_id}.forcing"
        if forcing.mode == "constant":
            nper = len(build_simulation_time_boundaries(simulation_window)) - 1
            resolved_flux = [float(forcing.as_constant().value)] * nper
        else:
            csv_cfg = forcing.as_csv()
            series = _load_well_csv_series(
                path_file=csv_cfg.path_file,
                sep=csv_cfg.sep,
                date_column=csv_cfg.date_column,
                date_format=csv_cfg.date_format,
                value_column=csv_cfg.value_column,
                label=label,
            )
            resolved_flux = _aggregate_well_series(
                series,
                simulation_window=simulation_window,
                label=label,
                aggregate=csv_cfg.aggregate,
            )

        updated_wells[well_id] = well_cfg.model_copy(
            update={"flux": resolved_flux, "forcing": None}
        )
        changed = True

    if not changed:
        return

    flow.set_sinks_sources(
        FlowSinksSourcesConfig(
            wells=updated_wells,
            recharge=sinks_sources.get("recharge") if isinstance(sinks_sources, Mapping) else None,
        )
    )
