"""On-the-fly derived fields computed from stored primary variables.

The store only persists primary variables (head, budget spatial fields,
surface_top).  Derived quantities like watertable_elevation, seepage_areas,
etc. are computed transparently by ``query_field()`` when not found in Zarr.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _get_surface_top(store: Any, sim_id: str) -> np.ndarray:
    """Read per-cell surface elevation from mesh group."""
    grp = store.open_zarr_group(sim_id)
    mesh = grp["mesh"]
    if "surface_top" in mesh:
        return np.asarray(mesh["surface_top"][:], dtype="float64")
    if "z_interfaces" in mesh:
        z = mesh["z_interfaces"][:]
        n_cells = int(mesh.attrs.get("n_cells", 1))
        return np.full(n_cells, float(z[0]), dtype="float64")
    raise KeyError(f"No surface elevation data for sim={sim_id}")


def _watertable_elevation(store: Any, sim_id: str, timestep: int) -> np.ndarray:
    """Water-table elevation: head at the uppermost saturated layer."""
    head = store.query_field(sim_id, "head", timestep)
    if head.ndim == 1:
        return head.copy()
    n_layers, n_cells = head.shape
    wt = np.full(n_cells, np.nan, dtype="float64")
    for lay in range(n_layers):
        mask = np.isfinite(head[lay]) & np.isnan(wt)
        wt[mask] = head[lay, mask]
    return wt


def _watertable_depth(store: Any, sim_id: str, timestep: int) -> np.ndarray:
    """Depth to water table: surface_top - watertable_elevation, clipped >= 0."""
    wt = store.query_field(sim_id, "watertable_elevation", timestep)
    top = _get_surface_top(store, sim_id)
    return np.maximum(top - wt, 0.0)


def _seepage_areas(store: Any, sim_id: str, timestep: int) -> np.ndarray:
    """Binary seepage indicator: 1 where watertable >= surface."""
    wt = store.query_field(sim_id, "watertable_elevation", timestep)
    top = _get_surface_top(store, sim_id)
    return (wt >= top).astype("float64")


def _drn_budget_field(store: Any, sim_id: str, timestep: int) -> np.ndarray:
    """Read raw DRN budget spatial field, raise KeyError if absent."""
    grp = store.open_zarr_group(sim_id)
    budget = grp.get("budget")
    if budget is None:
        raise KeyError("No budget spatial fields stored - enable budget.spatial_fields")
    for key in ("drn", "drain", "drains"):
        if key in budget:
            return np.asarray(budget[key][timestep], dtype="float64")
    raise KeyError("No drain budget field (DRN/DRAINS) in store")


def _outflow_drain(store: Any, sim_id: str, timestep: int) -> np.ndarray:
    """Per-cell drain outflow (signed), summed over layers."""
    drn = _drn_budget_field(store, sim_id, timestep)
    return drn.sum(axis=0) if drn.ndim == 2 else drn


# Registry: variable name -> computation function(store, sim_id, timestep)
# Only cheap derivations belong here.  accumulation_flux requires whitebox D8
# routing and must be pre-computed in the derive phase (see derived.py).
VIRTUAL_FIELDS: dict[str, Any] = {
    "watertable_elevation": _watertable_elevation,
    "watertable_depth": _watertable_depth,
    "seepage_areas": _seepage_areas,
    "outflow_drain": _outflow_drain,
}


def compute_virtual_field(
    store: Any,
    sim_id: str,
    variable: str,
    timestep: int,
) -> np.ndarray | None:
    """Compute a virtual field on-the-fly, or return None if unknown."""
    fn = VIRTUAL_FIELDS.get(variable)
    if fn is None:
        return None
    return fn(store, sim_id, timestep)
