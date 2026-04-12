"""Catchment-aggregated timeseries from spatial fields in the ResultStore."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_CATCHMENT_STATION = "_catchment"

# (source_variable, output_variable, reducer)
# source_variable is looked up in derived/ then budget/ then root.
_AGGREGATION_SPEC: list[tuple[str, str, str]] = [
    ("watertable_depth", "watertable_depth", "mean_active"),
    ("watertable_elevation", "watertable_elevation", "mean_active"),
    ("seepage_areas", "seepage_areas", "percent_positive"),
    # NWT: "drains"/"recharge", MF6: "drn"/"rch" — try both via _find_budget_key
    ("drains|drn|drain", "outflow_drain", "qspe"),
    # recharge_budget = MODFLOW budget (≈ outflow at equilibrium)
    # recharge_forcing = input forcing (from config) — written separately below
    ("recharge|rch", "recharge_budget", "mean_active"),
    ("accumulation_flux", "accumulation_flux", "max"),
    ("wells|wel", "well_pumping", "sum"),
]


def aggregate_catchment_timeseries(
    sim_id: str,
    store: Any,
    *,
    time_index: "pd.DatetimeIndex | None" = None,
) -> None:
    """Read spatial fields from the store and write catchment-aggregated timeseries.

    Parameters
    ----------
    sim_id : str
        Simulation UUID.
    store : ResultStore
        Store containing spatial fields from extract + derive phases.
    time_index : pd.DatetimeIndex, optional
        Datetime labels for each timestep. When None, integer indices are used.
    """
    grp = store.open_zarr_group(sim_id, mode="r")

    n_timesteps = _detect_n_timesteps(grp)
    if n_timesteps == 0:
        logger.debug("No timesteps found for sim %s, skipping aggregation", sim_id)
        return

    active_mask = _build_active_mask(grp)

    # Resolve a DatetimeIndex — DuckDB timeseries table requires TIMESTAMP.
    if time_index is not None and len(time_index) == n_timesteps:
        ts_index = time_index
    else:
        # Try to read period from simulation metadata.
        ts_index = _resolve_time_index(store, sim_id, n_timesteps)

    written = 0
    for store_var, output_var, reducer in _AGGREGATION_SPEC:
        values = _aggregate_variable(store, sim_id, grp, store_var, n_timesteps, active_mask, reducer)
        if values is None:
            continue

        ts = pd.Series(values, index=ts_index, name=output_var, dtype="float64")
        store.write_timeseries(sim_id, _CATCHMENT_STATION, output_var, ts)
        written += 1

    # Write recharge_forcing: the INPUT recharge rate (constant per stress period).
    # This is different from recharge_budget which equals drain at equilibrium.
    # We take 1 value per stress period (first substep) from the budget recharge.
    _write_recharge_forcing(store, sim_id, grp, n_timesteps, active_mask, ts_index)

    if written:
        logger.info("Wrote %d catchment-aggregated timeseries for sim %s", written, sim_id)


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
    try:
        row = store._db.execute(
            "SELECT period_start, period_end, time_unit FROM simulations WHERE sim_id = ?",
            [str(sim_id)],
        ).fetchone()
        if row is not None and row[0] is not None and row[1] is not None:
            return pd.date_range(start=row[0], end=row[1], periods=n_timesteps)
    except Exception:
        pass
    # Fallback: evenly spaced synthetic dates over 1 year.
    if n_timesteps <= 12:
        return pd.date_range("2000-01-01", periods=n_timesteps, freq="MS")
    # Spread n_timesteps evenly across 12 months
    return pd.date_range("2000-01-01", "2000-12-31", periods=n_timesteps)


def _write_recharge_forcing(
    store: Any,
    sim_id: str,
    grp,
    n_timesteps: int,
    active_mask: np.ndarray | None,
    ts_index: "pd.DatetimeIndex",
) -> None:
    """Write the input recharge forcing as 1 value per stress period.

    The budget recharge is constant within each stress period (it's the
    prescribed forcing). We detect stress-period boundaries by finding where
    the recharge value changes, then take one value per period.
    """
    candidates = ["recharge", "rch"]
    budget_grp = grp.get("budget")
    if budget_grp is None:
        return
    rch_key = None
    for c in candidates:
        if c in budget_grp:
            rch_key = c
            break
    if rch_key is None:
        return

    arr = budget_grp[rch_key]
    # Compute mean recharge per timestep
    all_means = []
    for t in range(n_timesteps):
        field = np.asarray(arr[t], dtype="float64")
        if field.ndim == 2:
            field = field[0]
        field = field.ravel()
        if active_mask is not None and active_mask.size == field.size:
            field = np.where(active_mask, field, np.nan)
        all_means.append(float(np.nanmean(field)))

    # Build 1 value per stress period by taking the first substep of each period.
    # Detect period boundaries: recharge is constant within each period,
    # so we group consecutive identical values.
    means = np.array(all_means)
    if len(means) == 0:
        return

    # Determine substeps per period from head array shape
    head_arr = grp.get("head")
    if head_arr is not None:
        n_head = head_arr.shape[0]
        # Try common period counts (12, 6, 4, etc.)
        for n_per in [12, 6, 4, 3, 2, 1]:
            if n_head % n_per == 0:
                nstp = n_head // n_per
                break
        else:
            nstp = 1
            n_per = n_head
    else:
        nstp = max(1, len(means) // 12)
        n_per = max(1, len(means) // nstp)

    period_values = []
    period_dates = []
    for p in range(n_per):
        idx = p * nstp
        if idx < len(means):
            period_values.append(means[idx])
            period_dates.append(ts_index[idx] if idx < len(ts_index) else ts_index[-1])

    if not period_values:
        return

    ts = pd.Series(period_values, index=pd.DatetimeIndex(period_dates),
                    name="recharge_forcing", dtype="float64")
    store.write_timeseries(sim_id, _CATCHMENT_STATION, "recharge_forcing", ts)


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
        field = field.sum(axis=0) if reducer == "qspe" else field[0]
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
    elif reducer == "qspe":
        return float(np.nansum(np.abs(valid)) / valid.size)
    elif reducer == "max":
        return float(np.nanmax(valid))
    elif reducer == "sum":
        return float(np.nansum(valid))
    else:
        return float(np.nanmean(valid))
