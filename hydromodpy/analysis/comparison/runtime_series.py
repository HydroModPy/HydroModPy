"""TimeSlice / VariableSeries dataclasses and store/disk loaders."""

from __future__ import annotations

import logging
import numbers
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.analysis.comparison.runtime_mesh import resolve_bundle_cells
from hydromodpy.analysis.comparison.runtime_physics import (
    _variable_candidates,
    is_nodata_value,
)
from hydromodpy.physics.flow.history_contract import (
    snapshot_elapsed_seconds_from_payload,
    step_end_elapsed_seconds_from_payload,
)

if TYPE_CHECKING:
    from hydromodpy.results.catalog import SimulationCatalog

logger = logging.getLogger(__name__)


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


def _sort_time_key(key: Any) -> tuple[int, float | str]:
    if isinstance(key, numbers.Real):
        return (0, float(key))
    text = str(key)
    try:
        return (0, float(text))
    except ValueError:
        return (1, text)


def _coerce_series_from_mapping(
    mapping: Mapping[Any, Any],
    *,
    variable_name: str,
    source_path: Path,
    cell_ids: np.ndarray | None = None,
) -> VariableSeries:
    slices = tuple(
        TimeSlice(
            time_key=key,
            time_index=index,
            values=np.asarray(value, dtype=float).ravel(),
        )
        for index, (key, value) in enumerate(
            sorted(mapping.items(), key=lambda item: _sort_time_key(item[0]))
        )
    )
    return VariableSeries(
        variable_name=variable_name,
        source_path=source_path,
        slices=slices,
        cell_ids=cell_ids,
    )


def _load_npy_series(path: Path, *, variable_name: str) -> VariableSeries:
    payload = np.load(path, allow_pickle=True)
    if getattr(payload, "shape", None) == () and hasattr(payload, "item"):
        item = payload.item()
        if isinstance(item, Mapping):
            return _coerce_series_from_mapping(
                item,
                variable_name=variable_name,
                source_path=path,
            )
    arr = np.asarray(payload, dtype=float)
    if arr.ndim <= 1:
        slices = (TimeSlice(time_key=0, time_index=0, values=arr.ravel()),)
    else:
        slices = tuple(
            TimeSlice(
                time_key=index,
                time_index=index,
                values=np.asarray(row, dtype=float).ravel(),
            )
            for index, row in enumerate(arr)
        )
    return VariableSeries(variable_name=variable_name, source_path=path, slices=slices)


def _load_mesh_npz_series(path: Path, *, variable_name: str) -> VariableSeries:
    payload = np.load(path, allow_pickle=True)
    values = np.asarray(payload["values"], dtype=float)
    if "time_index" in payload:
        time_keys = list(payload["time_index"])
    elif "times" in payload:
        time_keys = list(payload["times"])
    else:
        time_keys = list(range(values.shape[0] if values.ndim > 1 else 1))
    elapsed_seconds = (
        np.asarray(payload["times"], dtype=float).ravel() if "times" in payload else None
    )
    cell_ids = np.asarray(payload["cell_ids"], dtype=int) if "cell_ids" in payload else None
    if values.ndim <= 1:
        elapsed = (
            float(elapsed_seconds[0])
            if elapsed_seconds is not None and elapsed_seconds.size > 0
            else None
        )
        slices = (
            TimeSlice(
                time_key=time_keys[0],
                time_index=0,
                values=values.ravel(),
                elapsed_seconds=elapsed,
            ),
        )
    else:
        slices = tuple(
            TimeSlice(
                time_key=time_keys[index],
                time_index=index,
                values=values[index].ravel(),
                elapsed_seconds=(
                    float(elapsed_seconds[index])
                    if elapsed_seconds is not None and index < elapsed_seconds.size
                    else None
                ),
            )
            for index in range(values.shape[0])
        )
    return VariableSeries(
        variable_name=variable_name,
        source_path=path,
        slices=slices,
        cell_ids=cell_ids,
    )


def _load_boussinesq_npz_series(
    path: Path,
    *,
    variable_name: str,
) -> VariableSeries:
    payload = np.load(path, allow_pickle=True)
    if variable_name not in payload:
        raise KeyError(variable_name)
    values = np.asarray(payload[variable_name], dtype=float)
    period_lengths = (
        np.asarray(payload["period_lengths_seconds"], dtype=float).ravel()
        if "period_lengths_seconds" in payload
        else np.asarray([], dtype=float)
    )
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
        elapsed_seconds = snapshot_elapsed_seconds_from_payload(
            payload,
            n_snapshots=int(values.shape[0]),
        )
        is_snapshot_series = elapsed_seconds is not None
        if elapsed_seconds is None:
            elapsed_seconds = step_end_elapsed_seconds_from_payload(
                payload,
                n_steps=int(values.shape[0]),
            )
            is_snapshot_series = False
        if elapsed_seconds is None:
            elapsed_by_index = [None for _ in range(values.shape[0])]
        else:
            elapsed_by_index = [
                float(value) for value in np.asarray(elapsed_seconds, dtype=float).tolist()
            ]
        slices = tuple(
            TimeSlice(
                time_key=index,
                time_index=index,
                values=values[index].ravel(),
                elapsed_seconds=elapsed_by_index[index],
                is_initial_state=is_snapshot_series and index == 0,
            )
            for index in range(values.shape[0])
        )
    return VariableSeries(variable_name=variable_name, source_path=path, slices=slices)


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


def _load_boussinesq_surface_excess_total_series(
    run_folder: Path,
    path: Path,
    *,
    variable_name: str,
) -> VariableSeries:
    payload = np.load(path, allow_pickle=True)
    if "saturation_excess_history_m_s" not in payload:
        raise KeyError(variable_name)
    values = np.asarray(payload["saturation_excess_history_m_s"], dtype=float)
    if values.ndim == 1:
        values = values.reshape(1, -1)
    if values.ndim != 2:
        raise ValueError(
            "saturation_excess_history_m_s must be 2-D to derive surface-excess totals"
        )

    cells = resolve_bundle_cells(
        run_folder,
        expected_size=int(values.shape[1]),
    )
    if cells is None or cells.area_m2 is None:
        raise ValueError("Cannot derive surface_excess_total_m3_s without bundle cell areas")
    area_m2 = np.asarray(cells.area_m2, dtype=float).reshape(-1)
    if area_m2.size != values.shape[1]:
        raise ValueError("Bundle cell areas do not match saturation_excess_history_m_s width")

    positive = np.maximum(values, 0.0)
    totals_m3_s = np.sum(positive * area_m2[None, :], axis=1, dtype=float)
    period_lengths = (
        np.asarray(payload["period_lengths_seconds"], dtype=float).ravel()
        if "period_lengths_seconds" in payload
        else np.asarray([], dtype=float)
    )
    elapsed_seconds = snapshot_elapsed_seconds_from_payload(
        payload,
        n_snapshots=int(totals_m3_s.size),
    )
    if elapsed_seconds is None:
        elapsed_seconds = step_end_elapsed_seconds_from_payload(
            payload,
            n_steps=int(totals_m3_s.size),
        )
    if elapsed_seconds is None:
        elapsed_by_index = [None for _ in range(totals_m3_s.size)]
        has_initial_state = False
    else:
        elapsed_by_index = [
            float(value) for value in np.asarray(elapsed_seconds, dtype=float).tolist()
        ]
        has_initial_state = int(len(elapsed_by_index)) == int(totals_m3_s.size) and (
            bool(period_lengths.size) and int(totals_m3_s.size) == int(period_lengths.size) + 1
        )
    slices = tuple(
        TimeSlice(
            time_key=index,
            time_index=index,
            values=np.asarray([float(total)], dtype=float),
            elapsed_seconds=elapsed_by_index[index],
            is_initial_state=has_initial_state and index == 0,
        )
        for index, total in enumerate(totals_m3_s.tolist())
    )
    return VariableSeries(
        variable_name=variable_name,
        source_path=path,
        slices=slices,
        cell_ids=None,
    )


def _store_variable_mapping(variable_name: str) -> str | None:
    """Map a postprocess variable name to its SimulationCatalog field name.

    Returns ``None`` when no known mapping exists.
    """
    mapping: dict[str, str] = {
        "watertable_elevation": "watertable_elevation",
        "watertable_depth": "watertable_depth",
        "seepage_areas": "seepage_areas",
        "head": "head",
        "accumulation_flux": "accumulation_flux",
        "outflow_drain": "outflow_drain",
        "groundwater_flux": "groundwater_flux",
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
    """Try loading a variable series from the SimulationCatalog (Zarr fields).

    Returns ``None`` when the variable is not available in the store,
    allowing the caller to fall back to legacy loaders.
    """
    store_field = _store_variable_mapping(variable_name)
    if store_field is None:
        return None

    try:
        grp = store._open_zarr_group(sim_id)
    except (KeyError, Exception):
        return None

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
        source_path=Path(store.zarr_path),
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

    The Boussinesq extractor persists the full ``.npz`` content into a
    ``boussinesq_state`` Zarr subgroup.  This reader mirrors the logic
    of ``_load_boussinesq_npz_series`` but reads from Zarr instead of
    the on-disk ``.npz`` file.
    """
    try:
        grp = store._open_zarr_group(sim_id)
    except (KeyError, Exception):
        return None

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
            period_lengths = np.asarray(state_grp["period_lengths_seconds"][:], dtype=float).ravel()
        except Exception:
            pass

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
        source_path=Path(store.zarr_path),
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
    try:
        grp = store._open_zarr_group(sim_id)
    except (KeyError, Exception):
        return None

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
        source_path=Path(store.zarr_path),
        slices=slices,
        cell_ids=None,
    )


def load_variable_series(
    *,
    run_folder: Path,
    variable: str,
    store: SimulationCatalog | None = None,
    sim_id: str | None = None,
) -> VariableSeries:
    """Load one variable series, preferring SimulationCatalog when available.

    When *store* and *sim_id* are provided the function tries to read
    from the DuckDB+Zarr result store first.  If the variable is not
    found in the store (or the store is ``None``), it falls back to the
    legacy ``.npy`` / ``.npz`` loaders so existing workflows are not
    broken.
    """
    if store is not None and sim_id is not None:
        for variable_name in _variable_candidates(variable):
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

        logger.debug(
            "Variable '%s' not found in SimulationCatalog (sim_id=%s), "
            "falling back to legacy loaders.",
            variable,
            sim_id,
        )

    postprocess_dir = run_folder / "_postprocess"
    searched: list[Path] = []
    for variable_name in _variable_candidates(variable):
        npy_path = postprocess_dir / f"{variable_name}.npy"
        searched.append(npy_path)
        if npy_path.exists():
            return _load_npy_series(npy_path, variable_name=variable_name)

        mesh_npz_path = postprocess_dir / "_mesh" / f"flow_{variable_name}.npz"
        searched.append(mesh_npz_path)
        if mesh_npz_path.exists():
            return _load_mesh_npz_series(mesh_npz_path, variable_name=variable_name)

        boussinesq_path = run_folder / "_boussinesq_state_history.npz"
        searched.append(boussinesq_path)
        if boussinesq_path.exists():
            try:
                if variable_name in {
                    "surface_excess_total_m3_s",
                    "surface_threshold_total_m3_s",
                    "saturation_excess_total_m3_s",
                }:
                    return _load_boussinesq_surface_excess_total_series(
                        run_folder,
                        boussinesq_path,
                        variable_name=variable_name,
                    )
                return _load_boussinesq_npz_series(
                    boussinesq_path,
                    variable_name=variable_name,
                )
            except KeyError:
                pass

    searched_text = ", ".join(str(path) for path in searched)
    raise FileNotFoundError(
        f"Could not find postprocess variable '{variable}' in {run_folder}. "
        f"Searched: {searched_text}"
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
