"""Catchment-aggregated timeseries from spatial fields in the SimulationCatalog."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

_CATCHMENT_STATION = "_catchment"

VARIABLE_UNITS: dict[str, str] = {
    "discharge": "m3/s",
    "well_pumping": "m3/s",
}

# (source_variable, output_variable, reducer)
# source_variable is looked up in derived/ then budget/ then root.
#
# The catalog only materialises timeseries that downstream figures and
# calibration pipelines consume as-is. Catchment-scale reductions of
# spatial fields (drainage density, saturated fraction, water-table
# means, recharge means) are computed lazily on demand through
# ``hydromodpy.core.metrics`` / ``Run`` methods, so the
# catalog stays focused on observation-comparable point series.
_AGGREGATION_SPEC: list[tuple[str, str, str]] = [
    # Outlet discharge (m3/s) - sum of |drain flux| over the catchment,
    # consumed by hydrograph, watershed_id_card, calibration.
    ("drains|drn|drain", "discharge", "abs_sum"),
    # Well pumping total (m3/s).
    ("wells|wel", "well_pumping", "sum"),
]


def aggregate_catchment_timeseries(
    sim_id: str,
    store: Any,
    *,
    time_index: pd.DatetimeIndex | None = None,
) -> None:
    """Read spatial fields from the store and write catchment-aggregated timeseries.

    Parameters
    ----------
    sim_id : str
        Simulation UUID.
    store : SimulationCatalog
        Store containing spatial fields from extract + derive phases.
    time_index : pd.DatetimeIndex, optional
        Datetime labels for each timestep. When None, integer indices are used.
    """
    sz = store.open_zarr(sim_id)
    try:
        grp = sz.root

        n_timesteps = _detect_n_timesteps(grp)
        if n_timesteps == 0:
            raise RuntimeError(f"No timesteps found for sim {sim_id}; cannot aggregate catchment")

        active_mask = _build_active_mask(grp)

        pending: list[tuple[str, list[float]]] = []
        for store_var, output_var, reducer in _AGGREGATION_SPEC:
            values = _aggregate_variable(
                store, sim_id, grp, store_var, n_timesteps, active_mask, reducer
            )
            if values is None:
                continue
            pending.append((output_var, values))

        if not pending:
            return

        if time_index is not None and len(time_index) == n_timesteps:
            ts_index = time_index
        else:
            try:
                ts_index = _resolve_time_index(store, sim_id, n_timesteps)
            except RuntimeError as exc:
                logger.warning("Skipping catchment timeseries for sim %s: %s", sim_id, exc)
                return

        written = 0
        for output_var, values in pending:
            ts = pd.Series(values, index=ts_index, name=output_var, dtype="float64")
            if output_var == "discharge":
                ts = _add_runoff_to_discharge_series(ts, sim_id, store, grp)
            unit = VARIABLE_UNITS.get(output_var, "")
            store.write_timeseries(sim_id, _CATCHMENT_STATION, output_var, ts, unit=unit)
            written += 1
    finally:
        sz.close()

    if written:
        logger.info("Wrote %d catchment-aggregated timeseries for sim %s", written, sim_id)


def _add_runoff_to_discharge_series(
    discharge: pd.Series,
    sim_id: str,
    store: Any,
    grp: Any,
) -> pd.Series:
    """Add the surface-runoff forcing (m³/s) to a baseflow series.

    The forcing is read from the Zarr ``forcing/runoff/<station>/values``
    arrays persisted by ``step_persist_forcings``. Stations are averaged
    in mm/day, resampled to the simulation index, then converted to m³/s
    using the catchment area read from ``geographic_metadata``. When no
    runoff forcing is found, a one-shot warning is emitted and the
    baseflow is returned unchanged.
    """
    runoff_grp = None
    forcing = grp.get("forcing")
    if forcing is not None and "runoff" in forcing:
        runoff_grp = forcing["runoff"]
    if runoff_grp is None:
        if sim_id not in _RUNOFF_WARNING_EMITTED:
            logger.warning(
                "catchment discharge: no runoff forcing in Zarr for sim %s — "
                "writing DRN baseflow only (mismatch with total streamflow obs).",
                sim_id,
            )
            _RUNOFF_WARNING_EMITTED.add(sim_id)
        return discharge

    catch_area_m2 = _read_catchment_area_m2(store, sim_id)
    if catch_area_m2 <= 0.0:
        logger.warning(
            "catchment discharge: catchment area unavailable for sim %s — "
            "skipping runoff addition.",
            sim_id,
        )
        return discharge

    series_list: list[pd.Series] = []
    for station_key in list(runoff_grp.array_keys()) + list(runoff_grp.group_keys()):
        node = runoff_grp[station_key]
        if hasattr(node, "shape"):
            # Flat array case (older layout); skip without timestamps.
            continue
        if "values" not in node or "timestamps" not in node:
            continue
        values_arr = np.asarray(node["values"][:], dtype="float64")
        timestamps_arr = np.asarray(node["timestamps"][:])
        if values_arr.size == 0:
            continue
        idx = pd.DatetimeIndex(pd.to_datetime(timestamps_arr))
        series_list.append(pd.Series(values_arr, index=idx))
    if not series_list:
        return discharge

    runoff_mm_per_d = pd.concat(series_list, axis=1).mean(axis=1)
    target_index = discharge.index
    runoff_index = runoff_mm_per_d.index
    if runoff_index.tz is None and target_index.tz is not None:
        runoff_mm_per_d = runoff_mm_per_d.tz_localize(target_index.tz)
    elif runoff_index.tz is not None and target_index.tz is None:
        runoff_mm_per_d = runoff_mm_per_d.tz_localize(None)
    elif runoff_index.tz is not None and target_index.tz is not None:
        runoff_mm_per_d = runoff_mm_per_d.tz_convert(target_index.tz)
    aligned = runoff_mm_per_d.reindex(target_index, method="nearest")
    runoff_m3_per_s = aligned * 1e-3 * catch_area_m2 / 86400.0
    return discharge.add(runoff_m3_per_s, fill_value=0.0)


_RUNOFF_WARNING_EMITTED: set[str] = set()


def _read_catchment_area_m2(store: Any, sim_id: str) -> float:
    """Return the catchment area in m² from ``geographic_metadata``."""
    conn = getattr(store, "connection", None) or store._db
    row = conn.execute(
        "SELECT value FROM geographic_metadata WHERE sim_id = ? AND key = 'catch_area'",
        [str(sim_id)],
    ).fetchone()
    if row is not None and row[0] is not None:
        return float(row[0]) * 1e6
    return 0.0


def _aggregate_variable(
    store: Any,
    sim_id: str,
    grp,
    store_var: str,
    n_timesteps: int,
    active_mask: np.ndarray | None,
    reducer: str,
) -> list[float] | None:
    """Try to read *store_var* for all timesteps, aggregate, and return scalar list."""
    # Locate the variable in derived/, budget/, or root.
    # store_var may contain "|" alternatives (e.g., "drains|drn|drain").
    candidates = [s.strip() for s in store_var.split("|")]
    derived_grp = grp.get("derived")
    budget_grp = grp.get("budget")

    target_grp = None
    resolved_key = None
    for key in candidates:
        if derived_grp is not None and key in derived_grp:
            target_grp, resolved_key = derived_grp, key
            break
        if budget_grp is not None and key in budget_grp:
            target_grp, resolved_key = budget_grp, key
            break
        if key in grp:
            target_grp, resolved_key = grp, key
            break

    if target_grp is None or resolved_key is None:
        return None

    arr = target_grp[resolved_key]

    values = []
    for t in range(n_timesteps):
        try:
            field = np.asarray(arr[t], dtype="float64")
        except (IndexError, KeyError):
            return None
        scalar = _reduce(field, active_mask, reducer)
        values.append(scalar)

    return values


def _resolve_time_index(store: Any, sim_id: str, n_timesteps: int) -> pd.DatetimeIndex:
    """Build a DatetimeIndex from simulation metadata or synthetic."""
    conn = getattr(store, "connection", None) or store._db
    row = conn.execute(
        "SELECT period_start, period_end, time_unit FROM simulations WHERE sim_id = ?",
        [str(sim_id)],
    ).fetchone()
    if row is not None and row[0] is not None and row[1] is not None:
        return pd.date_range(start=row[0], end=row[1], periods=n_timesteps)
    raise RuntimeError(
        f"Simulation {sim_id} is missing period_start/period_end; "
        "cannot write catchment timeseries with synthetic timestamps."
    )


def _detect_n_timesteps(grp) -> int:
    """Detect number of timesteps from head or derived arrays."""
    if "head" in grp:
        return grp["head"].shape[0]
    derived = grp.get("derived")
    if derived is not None:
        for key in derived:
            return derived[key].shape[0]
    return 0


def _build_active_mask(grp) -> np.ndarray | None:
    """Build boolean mask of active cells from mesh surface_top."""
    mesh = grp.get("mesh")
    if mesh is None:
        return None
    if "surface_top" in mesh:
        top = np.asarray(mesh["surface_top"][:], dtype="float64").ravel()
        return np.isfinite(top) & (top > -9000)
    return None


def _reduce(field: np.ndarray, mask: np.ndarray | None, reducer: str) -> float:
    """Reduce a spatial field to a single scalar."""
    # Flatten multi-layer fields to single layer
    if field.ndim == 2:
        field = field.sum(axis=0) if reducer in ("abs_sum", "sum") else field[0]
    field = field.ravel().astype("float64")

    if mask is not None and mask.size == field.size:
        field = np.where(mask, field, np.nan)
    else:
        field = np.where(field > -9000, field, np.nan)

    valid = field[np.isfinite(field)]
    if valid.size == 0:
        return float("nan")

    if reducer == "mean_active":
        return float(np.nanmean(valid))
    elif reducer == "percent_positive":
        n_positive = np.count_nonzero(valid > 0)
        return float(n_positive / valid.size * 100)
    elif reducer == "abs_sum":
        return float(np.nansum(np.abs(valid)))
    elif reducer == "max":
        return float(np.nanmax(valid))
    elif reducer == "sum":
        return float(np.nansum(valid))
    else:
        return float(np.nanmean(valid))
