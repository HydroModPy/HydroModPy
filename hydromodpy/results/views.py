"""Lazy catchment-scale views computed on demand from a SimulationView.

These functions read already-persisted spatial fields (``derived/`` and
``budget/`` groups in the simulation Zarr) and reduce them to scalar
timeseries on the fly. Nothing is written to DuckDB: results are returned
as ``pd.Series`` so that callers can plot, combine or aggregate them
freely.

All functions are pure — they take a :class:`SimulationView` (or any
object exposing the same ``field`` / ``n_timesteps`` / ``mesh`` API) and
the reduction parameters, and return a new object. They never mutate the
catalog.

Standard Python pattern: the module-level function is the source of
truth; :class:`SimulationView` exposes thin delegate methods for
ergonomics (``sim.drainage_density(...)`` calls
:func:`drainage_density`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from hydromodpy.results.simulation import SimulationView


__all__ = [
    "saturated_fraction",
    "drainage_density",
    "persistence",
    "catchment_mean",
    "recharge_forcing",
]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _time_index(sim: "SimulationView", n: int) -> pd.DatetimeIndex:
    """Return a ``pd.DatetimeIndex`` aligned with the simulation timesteps."""
    row = sim._load_row()
    start, end = row.get("period_start"), row.get("period_end")
    if start is not None and end is not None:
        return pd.date_range(start=start, end=end, periods=n)
    return pd.date_range("2000-01-01", periods=n, freq="D")


def _catchment_mask(sim: "SimulationView") -> np.ndarray | None:
    """Boolean mask of active cells from ``mesh/surface_top``."""
    sz = sim._catalog.open_zarr(sim._sim_id)
    mesh = sz.root.get("mesh")
    if mesh is None or "surface_top" not in mesh:
        return None
    top = np.asarray(mesh["surface_top"][:], dtype="float64").ravel()
    return np.isfinite(top) & (top > -9000.0)


def _stack_field(sim: "SimulationView", variable: str) -> np.ndarray:
    """Stack a per-timestep cell field into a ``(n_t, n_cells)`` array."""
    n = sim.n_timesteps or 1
    frames = [np.asarray(sim.field(variable, timestep=t)).ravel() for t in range(n)]
    return np.stack(frames)


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------


def saturated_fraction(
    sim: "SimulationView",
    *,
    threshold: float = 0.0,
) -> pd.Series:
    """Fraction of active catchment cells where seepage exceeds ``threshold``.

    Reads ``derived/seepage_areas`` (m) from the simulation Zarr and
    reduces each timestep to the percentage of active cells above the
    threshold. Unit: ``%``.
    """
    mask = _catchment_mask(sim)
    stack = _stack_field(sim, "seepage_areas")
    if mask is None:
        mask = np.ones(stack.shape[1], dtype=bool)
    n_active = int(mask.sum())
    if n_active == 0:
        return pd.Series(dtype="float64", name="saturated_fraction")
    active = (stack > threshold) & mask
    pct = 100.0 * active.sum(axis=1) / n_active
    return pd.Series(pct, index=_time_index(sim, stack.shape[0]),
                     name="saturated_fraction")


def drainage_density(
    sim: "SimulationView",
    *,
    threshold: float = 0.0,
) -> pd.Series:
    """Fraction of active catchment cells whose routed drain flux is positive.

    Reads ``derived/accumulation_flux`` (m³/d) from the simulation Zarr
    and returns the fraction of active cells above ``threshold``, per
    timestep. Unit: ``%``.

    Matches the headwater-study definition of "active drainage density"
    (stream-network occupation of the catchment).
    """
    mask = _catchment_mask(sim)
    stack = _stack_field(sim, "accumulation_flux")
    if mask is None:
        mask = np.ones(stack.shape[1], dtype=bool)
    n_active = int(mask.sum())
    if n_active == 0:
        return pd.Series(dtype="float64", name="drainage_density")
    active = (stack > threshold) & mask
    pct = 100.0 * active.sum(axis=1) / n_active
    return pd.Series(pct, index=_time_index(sim, stack.shape[0]),
                     name="drainage_density")


def persistence(
    sim: "SimulationView",
    *,
    variable: str = "accumulation_flux",
    threshold: float = 0.0,
    window: Literal["year", "full"] = "full",
) -> np.ndarray:
    """Per-cell fraction of timesteps where ``variable`` exceeds ``threshold``.

    ``window='full'`` reduces over the whole simulation and returns a 1D
    array of length ``n_cells``. ``window='year'`` groups by calendar
    year and returns a 2D array ``(n_years, n_cells)``.
    """
    stack = _stack_field(sim, variable)
    active = stack > threshold
    if window == "full":
        return active.mean(axis=0)
    if window == "year":
        idx = _time_index(sim, stack.shape[0])
        frame = pd.DataFrame(active, index=idx)
        return frame.groupby(frame.index.year).mean().to_numpy()
    raise ValueError(f"Unknown window '{window}'")


def catchment_mean(
    sim: "SimulationView",
    variable: str,
    *,
    name: str | None = None,
) -> pd.Series:
    """Arithmetic mean of ``variable`` over active catchment cells per timestep.

    Works for any cell-scalar variable persisted under ``derived/`` or
    ``budget/`` (e.g. ``watertable_depth``, ``watertable_elevation``).
    """
    mask = _catchment_mask(sim)
    stack = _stack_field(sim, variable)
    if mask is None:
        mask = np.ones(stack.shape[1], dtype=bool)
    if not mask.any():
        return pd.Series(dtype="float64", name=name or variable)
    masked = np.where(mask[None, :], stack, np.nan)
    means = np.nanmean(masked, axis=1)
    return pd.Series(means, index=_time_index(sim, stack.shape[0]),
                     name=name or variable)


def recharge_forcing(sim: "SimulationView") -> pd.Series:
    """Input recharge rate per stress period (from ``budget/recharge``).

    Reads the first substep of each stress period from the MODFLOW
    budget; constant within a period by the forcing contract.
    """
    sz = sim._catalog.open_zarr(sim._sim_id)
    budget = sz.root.get("budget")
    if budget is None:
        return pd.Series(dtype="float64", name="recharge_forcing")
    rch_key = next((k for k in ("recharge", "rch") if k in budget), None)
    if rch_key is None:
        return pd.Series(dtype="float64", name="recharge_forcing")

    arr = budget[rch_key]
    n_t = arr.shape[0]
    mask = _catchment_mask(sim)
    means = []
    for t in range(n_t):
        field = np.asarray(arr[t], dtype="float64").ravel()
        if mask is not None and mask.size == field.size:
            field = np.where(mask, field, np.nan)
        means.append(float(np.nanmean(field)))

    return pd.Series(means, index=_time_index(sim, n_t),
                     name="recharge_forcing")
