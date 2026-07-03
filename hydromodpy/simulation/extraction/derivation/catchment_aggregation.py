"""Catchment-aggregated timeseries from spatial fields in the Catalog."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

_CATCHMENT_STATION = "_catchment"

_SLAB_TARGET_BYTES = 64 * 1024 * 1024

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
    # Direct drain outflow (m3/s) - sum of |drain flux| over the catchment.
    # The MVR-routed share lives in the separate DRN-TO-MVR budget record and
    # is therefore excluded: it re-enters the model through SFR and surfaces
    # in the routed ext_outflow series instead.
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

    The ``discharge`` series is the surface water leaving the catchment. When
    the run carries SFR / LAK extracted series, the discharge IS the routed
    outflow (``ext_outflow`` at terminal reaches and lake outlets), which already
    carries the in-watershed drainage (routed through DRN-TO-MVR) and the runoff
    injected into the network; the residual plain-DRN record is buffer drainage
    from neighbouring basins and is excluded. Without a stream network the series
    falls back to the lumped accounting: sum of |DRN| plus the watershed runoff
    forcing read from Zarr ``forcing/``.

    Parameters
    ----------
    sim_id : str
        Simulation UUID.
    store : Catalog
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

        routed = _routed_outflow_by_timestep(store, sim_id, n_timesteps)
        if not pending and routed is None:
            return

        if time_index is not None and len(time_index) == n_timesteps:
            ts_index = time_index
        else:
            try:
                ts_index = _resolve_time_index(store, sim_id, n_timesteps)
            except RuntimeError as exc:
                logger.warning("Skipping catchment timeseries for sim %s: %s", sim_id, exc)
                return

        series_by_var: dict[str, pd.Series] = {
            output_var: pd.Series(values, index=ts_index, name=output_var, dtype="float64")
            for output_var, values in pending
        }
        if routed is not None:
            # The routed SFR/LAK ext_outflow already carries the in-watershed
            # drainage (moved into the DRN-TO-MVR record by route_drainage, whose
            # plain-DRN residual is ~0). The remaining plain-DRN outflow is the
            # buffer (neighbouring-basin) drainage, which must NOT feed this
            # catchment, so it is dropped instead of added.
            series_by_var["discharge"] = pd.Series(
                routed, index=ts_index, name="discharge", dtype="float64"
            )
            _warn_routed_without_runoff(store, sim_id, grp)
            logger.debug("Catchment discharge for sim %s uses routed SFR/LAK outflow", sim_id)
        elif "discharge" in series_by_var:
            series_by_var["discharge"] = _add_runoff_to_discharge_series(
                series_by_var["discharge"], sim_id, store, grp
            )

        written = 0
        for output_var, ts in series_by_var.items():
            unit = VARIABLE_UNITS.get(output_var, "")
            store.write_timeseries(sim_id, _CATCHMENT_STATION, output_var, ts, unit=unit)
            written += 1
    finally:
        sz.close()

    if written:
        logger.debug("Wrote %d catchment-aggregated timeseries for sim %s", written, sim_id)


_ROUTED_RUNOFF_WARNING_EMITTED: set[str] = set()


def _warn_routed_without_runoff(store: Any, sim_id: str, grp: Any) -> None:
    """Warn once if runoff forcing exists but was not routed into SFR/LAK.

    The routed discharge assumes the runoff was injected into the network; if a
    run carries runoff forcing in Zarr but no runoff was wired to any SFR/lake
    station, the routed discharge silently omits it.
    """
    if sim_id in _ROUTED_RUNOFF_WARNING_EMITTED:
        return
    forcing = grp.get("forcing")
    if forcing is None or "runoff" not in forcing:
        return
    try:
        row = store.connection.execute(
            "SELECT 1 FROM timeseries WHERE sim_id = ? AND variable = 'runoff' "
            "AND (station_id LIKE 'sfr:%' OR station_id LIKE 'lake:%') LIMIT 1",
            [str(sim_id)],
        ).fetchone()
    except Exception:
        return
    if row is None:
        logger.warning(
            "catchment discharge: runoff forcing is present for sim %s but no runoff was "
            "routed into SFR/LAK; the routed discharge excludes the runoff component.",
            sim_id,
        )
        _ROUTED_RUNOFF_WARNING_EMITTED.add(sim_id)


def _routed_outflow_by_timestep(
    store: Any,
    sim_id: str,
    n_timesteps: int,
) -> np.ndarray | None:
    """Sum of ext_outflow over SFR reaches and lake outlets, per timestep.

    ``ext_outflow`` is the surface water leaving the model at a terminal reach or
    a lake outlet (stations ``sfr:*`` / ``lake:*``, extracted from the MF6 obs
    CSVs in m3/s). Both extractors store it with the same positive-outflow
    convention. Returns None when no such series exists (no SFR / LAK run).
    """
    try:
        rows = store.connection.execute(
            "SELECT timestep, SUM(value) FROM timeseries "
            "WHERE sim_id = ? AND variable = 'ext_outflow' "
            "  AND (station_id LIKE 'sfr:%' OR station_id LIKE 'lake:%') "
            "GROUP BY timestep",
            [str(sim_id)],
        ).fetchall()
    except Exception:
        logger.debug("No readable timeseries table for sim %s", sim_id, exc_info=True)
        return None
    if not rows:
        return None
    values = np.zeros(n_timesteps, dtype="float64")
    for timestep, total in rows:
        t = int(timestep)
        if 0 <= t < n_timesteps and total is not None:
            values[t] = float(total)
    return values


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
    conn = store.connection
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
    if arr.shape[0] < n_timesteps:
        return None

    # Slab reads: one Zarr selection per block instead of one per timestep.
    bytes_per_step = max(int(np.prod(arr.shape[1:])) * 8, 1)
    block = max(1, min(n_timesteps, _SLAB_TARGET_BYTES // bytes_per_step))

    values: list[float] = []
    for t0 in range(0, n_timesteps, block):
        t1 = min(t0 + block, n_timesteps)
        fields = np.asarray(arr[t0:t1], dtype="float64")
        for field in fields:
            values.append(_reduce(field, active_mask, reducer))

    return values


def _resolve_time_index(store: Any, sim_id: str, n_timesteps: int) -> pd.DatetimeIndex:
    """Return the catchment series time axis, sharing the solver's clock.

    The aggregation reduces the Zarr field arrays, so it reuses their CF
    ``/time`` axis: the exact stress-period timestamps the solver wrote. This
    keeps the derived catchment series on the same clock as the native solver
    series (head, stage, budgets) instead of re-deriving a
    ``date_range(..., periods=n)`` that drifts (n-1 intervals over the window).
    Falls back to the catalog ``period_start/period_end`` only when the axis is
    unavailable.
    """
    times = _read_solver_time_axis(store, sim_id)
    if times is not None and len(times) == n_timesteps:
        return pd.DatetimeIndex(times)

    conn = store.connection
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


def _read_solver_time_axis(store: Any, sim_id: str) -> np.ndarray | None:
    """Read the persisted CF ``/time`` axis via the injected store (duck-typed)."""
    opener = getattr(store, "open_zarr", None)
    if not callable(opener):
        return None
    try:
        with opener(sim_id) as store_zarr:
            return store_zarr.read_time()
    except Exception:
        return None


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
    """Build boolean mask of active cells from mesh topography."""
    mesh = grp.get("mesh")
    if mesh is None:
        return None
    if "topography" in mesh:
        top = np.asarray(mesh["topography"][:], dtype="float64").ravel()
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
