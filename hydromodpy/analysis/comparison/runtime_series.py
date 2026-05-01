"""TimeSlice / VariableSeries dataclasses and Zarr store loaders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.analysis.comparison.runtime_mesh import resolve_bundle_cells
from hydromodpy.analysis.comparison.runtime_physics import (
    _variable_candidates,
    is_nodata_value,
)
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.results.catalog import SimulationCatalog

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TimeSlice:
    """One variable payload at one simulation time index."""

    time_key: Any
    time_index: int
    values: np.ndarray
    elapsed_seconds: float | None = None
    is_initial_state: bool = False


@dataclass(frozen=True, slots=True)
class VariableSeries:
    """Loaded postprocess variable series."""

    variable_name: str
    source_path: Path
    slices: tuple[TimeSlice, ...]
    cell_ids: np.ndarray | None = None


def _elapsed_seconds_from_period_lengths(
    *,
    n_snapshots: int,
    period_lengths: np.ndarray,
) -> list[float | None]:
    if n_snapshots <= 0:
        return []
    if period_lengths.size == n_snapshots - 1:
        elapsed: list[float | None] = [0.0]
        elapsed.extend(float(value) for value in np.cumsum(period_lengths))
        return elapsed
    if period_lengths.size == n_snapshots:
        return [float(value) for value in np.cumsum(period_lengths)]
    return [None for _ in range(n_snapshots)]


def _store_variable_mapping(variable_name: str) -> str | None:
    """Map a postprocess variable name to its SimulationCatalog field name.

    Returns ``None`` when no known mapping exists.
    """
    mapping: dict[str, str] = {
        "watertable_elevation": "watertable_elevation",
        "watertable_depth": "watertable_depth",
        "seepage_mask": "seepage_mask",
        "head": "head",
        "accumulation_flux": "accumulation_flux",
        "outflow_drain": "outflow_drain",
        "groundwater_flux": "groundwater_flux",
        "outlet_discharge_east_side_m3_s": "outlet_discharge_east_side_m3_s",
        "drainage_flux_history_m3_s": "drainage_flux_history_m3_s",
        "drainage_flux_m3_s": "drainage_flux_m3_s",
        "concentration_seepage": "concentration_seepage",
        "mass_seepage": "mass_seepage",
        "mass_accumulated": "mass_accumulated",
    }
    return mapping.get(variable_name.strip().lower())


def _load_store_series(
    store: SimulationCatalog,
    sim_id: str,
    *,
    variable_name: str,
) -> VariableSeries | None:
    """Try loading a variable series from the SimulationCatalog (Zarr fields)."""
    store_field = _store_variable_mapping(variable_name)
    if store_field is None:
        return None

    sz = None
    try:
        sz = store.open_zarr(sim_id)
        grp = sz.root
    except (KeyError, Exception):
        return None
    try:
        arr = None
        for loc in (grp, grp.get("derived"), grp.get("budget")):
            if loc is not None and store_field in loc:
                arr = loc[store_field]
                break
        if arr is None:
            return None

        try:
            data = arr[:]
        except Exception:
            return None
    finally:
        if sz is not None:
            sz.close()

    if data.ndim == 0:
        return None

    if data.ndim == 1:
        slices = (
            TimeSlice(
                time_key=0,
                time_index=0,
                values=np.asarray(data, dtype=float).ravel(),
            ),
        )
    else:
        slices = tuple(
            TimeSlice(
                time_key=t,
                time_index=t,
                values=np.asarray(data[t], dtype=float).ravel(),
            )
            for t in range(data.shape[0])
        )

    if not slices:
        return None

    return VariableSeries(
        variable_name=variable_name,
        source_path=_store_source_path(store, sim_id),
        slices=slices,
        cell_ids=None,
    )


def _load_store_boussinesq_state_series(
    store: SimulationCatalog,
    sim_id: str,
    *,
    variable_name: str,
) -> VariableSeries | None:
    """Try loading a Boussinesq state history variable from the store.

    The Boussinesq extractor persists state history into a
    ``boussinesq_state`` Zarr subgroup.
    """
    sz = None
    try:
        sz = store.open_zarr(sim_id)
        grp = sz.root
    except (KeyError, Exception):
        return None

    try:
        state_grp = grp.get("boussinesq_state")
        if state_grp is None or variable_name not in state_grp:
            return None

        try:
            values = np.asarray(state_grp[variable_name][:], dtype=float)
        except Exception:
            return None

        period_lengths = np.asarray([], dtype=float)
        if "period_lengths_seconds" in state_grp:
            try:
                period_lengths = np.asarray(
                    state_grp["period_lengths_seconds"][:], dtype=float
                ).ravel()
            except Exception:
                pass
    finally:
        if sz is not None:
            sz.close()

    if values.ndim <= 1:
        elapsed = float(np.nansum(period_lengths)) if period_lengths.size > 0 else None
        slices = (
            TimeSlice(
                time_key="final",
                time_index=max(0, int(period_lengths.size)),
                values=values.ravel(),
                elapsed_seconds=elapsed,
            ),
        )
    else:
        elapsed_by_index = _elapsed_seconds_from_period_lengths(
            n_snapshots=int(values.shape[0]),
            period_lengths=period_lengths,
        )
        slices = tuple(
            TimeSlice(
                time_key=index,
                time_index=index,
                values=values[index].ravel(),
                elapsed_seconds=elapsed_by_index[index],
                is_initial_state=period_lengths.size == values.shape[0] - 1 and index == 0,
            )
            for index in range(values.shape[0])
        )

    return VariableSeries(
        variable_name=variable_name,
        source_path=_store_source_path(store, sim_id),
        slices=slices,
        cell_ids=None,
    )


def _load_store_surface_excess_total_series(
    store: SimulationCatalog,
    sim_id: str,
    *,
    variable_name: str,
    run_folder: Path,
) -> VariableSeries | None:
    """Try loading surface-excess totals from the store.

    Mirrors ``_load_boussinesq_surface_excess_total_series`` but reads
    the ``saturation_excess_history_m_s`` array from the Zarr
    ``boussinesq_state`` group.
    """
    sz = None
    try:
        sz = store.open_zarr(sim_id)
        grp = sz.root
    except (KeyError, Exception):
        return None

    try:
        state_grp = grp.get("boussinesq_state")
        if state_grp is None or "saturation_excess_history_m_s" not in state_grp:
            return None

        try:
            values = np.asarray(
                state_grp["saturation_excess_history_m_s"][:],
                dtype=float,
            )
        except Exception:
            return None

        if values.ndim == 1:
            values = values.reshape(1, -1)
        if values.ndim != 2:
            return None

        cells = resolve_bundle_cells(
            run_folder,
            expected_size=int(values.shape[1]),
        )
        if cells is None or cells.area_m2 is None:
            return None
        area_m2 = np.asarray(cells.area_m2, dtype=float).reshape(-1)
        if area_m2.size != values.shape[1]:
            return None

        positive = np.maximum(values, 0.0)
        totals_m3_s = np.sum(positive * area_m2[None, :], axis=1, dtype=float)

        period_lengths = np.asarray([], dtype=float)
        if "period_lengths_seconds" in state_grp:
            try:
                period_lengths = np.asarray(
                    state_grp["period_lengths_seconds"][:],
                    dtype=float,
                ).ravel()
            except Exception:
                pass
    finally:
        if sz is not None:
            sz.close()

    elapsed_by_index = _elapsed_seconds_from_period_lengths(
        n_snapshots=int(totals_m3_s.size),
        period_lengths=period_lengths,
    )
    slices = tuple(
        TimeSlice(
            time_key=index,
            time_index=index,
            values=np.asarray([float(total)], dtype=float),
            elapsed_seconds=elapsed_by_index[index],
            is_initial_state=period_lengths.size == totals_m3_s.size - 1 and index == 0,
        )
        for index, total in enumerate(totals_m3_s.tolist())
    )
    return VariableSeries(
        variable_name=variable_name,
        source_path=_store_source_path(store, sim_id),
        slices=slices,
        cell_ids=None,
    )


def _store_source_path(store: SimulationCatalog, sim_id: str) -> Path:
    zarr_path_for = getattr(store, "zarr_path_for", None)
    if callable(zarr_path_for):
        return Path(zarr_path_for(sim_id))
    return Path(getattr(store, "zarr_path", ""))


def load_variable_series(
    *,
    run_folder: Path,
    variable: str,
    store: SimulationCatalog | None = None,
    sim_id: str | None = None,
) -> VariableSeries:
    """Load one variable series from the DuckDB+Zarr result store."""
    if store is None or sim_id is None:
        raise ValueError("load_variable_series requires a SimulationCatalog and sim_id.")

    searched: list[str] = []
    for variable_name in _variable_candidates(variable):
        searched.append(variable_name)
        series = _load_store_series(store, sim_id, variable_name=variable_name)
        if series is not None:
            logger.debug(
                "Loaded '%s' from SimulationCatalog (sim_id=%s).",
                variable_name,
                sim_id,
            )
            return series

        if variable_name in {
            "surface_excess_total_m3_s",
            "surface_threshold_total_m3_s",
            "saturation_excess_total_m3_s",
        }:
            series = _load_store_surface_excess_total_series(
                store,
                sim_id,
                variable_name=variable_name,
                run_folder=run_folder,
            )
        else:
            series = _load_store_boussinesq_state_series(
                store,
                sim_id,
                variable_name=variable_name,
            )
        if series is not None:
            logger.debug(
                "Loaded '%s' from SimulationCatalog boussinesq_state (sim_id=%s).",
                variable_name,
                sim_id,
            )
            return series

    searched_text = ", ".join(searched)
    raise FileNotFoundError(
        f"Could not find variable '{variable}' in SimulationCatalog sim_id={sim_id}. "
        f"Tried variables: {searched_text}"
    )


def mask_depth_series_from_head_nodata(
    *,
    run_folder: Path,
    series: VariableSeries,
    store: SimulationCatalog | None = None,
    sim_id: str | None = None,
) -> VariableSeries:
    """Mask `watertable_depth` where the companion head series carries nodata."""
    if series.variable_name.strip().lower() != "watertable_depth":
        return series

    try:
        head_series = load_variable_series(
            run_folder=run_folder,
            variable="watertable_elevation",
            store=store,
            sim_id=sim_id,
        )
    except Exception:
        return series

    if len(head_series.slices) != len(series.slices):
        return series

    masked_slices: list[TimeSlice] = []
    for depth_slice, head_slice in zip(series.slices, head_series.slices, strict=False):
        depth_values = np.asarray(depth_slice.values, dtype=float).ravel().copy()
        head_values = np.asarray(head_slice.values, dtype=float).ravel()
        if depth_values.size != head_values.size:
            return series
        nodata_mask = np.asarray(
            [is_nodata_value(value) for value in head_values],
            dtype=bool,
        )
        if nodata_mask.size == depth_values.size and np.any(nodata_mask):
            depth_values[nodata_mask] = np.nan
        masked_slices.append(
            TimeSlice(
                time_key=depth_slice.time_key,
                time_index=depth_slice.time_index,
                values=depth_values,
                elapsed_seconds=depth_slice.elapsed_seconds,
                is_initial_state=depth_slice.is_initial_state,
            )
        )

    return VariableSeries(
        variable_name=series.variable_name,
        source_path=series.source_path,
        slices=tuple(masked_slices),
        cell_ids=series.cell_ids,
    )


__all__ = (
    "TimeSlice",
    "VariableSeries",
    "load_variable_series",
    "mask_depth_series_from_head_nodata",
)
