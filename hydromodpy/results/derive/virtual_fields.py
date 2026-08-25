"""On-the-fly derived fields computed from stored primary variables.

The store only persists primary variables (head, budget spatial fields,
topography). Derived quantities like watertable_elevation and seepage_mask
are computed transparently by ``query_field()`` when not found in Zarr.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from hydromodpy.core.field_routing import (
    drain_budget_to_positive_outflow,
    find_drain_budget_key,
    seepage_mask,
    warn_on_geometric_seepage_fallback,
)
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


def _get_topography(store: Any, sim_id: str) -> np.ndarray:
    """Read per-cell surface elevation from mesh group."""
    sz = store.open_zarr(sim_id)
    try:
        mesh = sz.root["mesh"]
        if "topography" in mesh:
            return np.asarray(mesh["topography"][:], dtype="float64")
        if "z_interfaces" in mesh:
            z = mesh["z_interfaces"][:]
            n_cells = int(mesh.attrs.get("n_cells", 1))
            return np.full(n_cells, float(z[0]), dtype="float64")
        raise KeyError(f"No surface elevation data for sim={sim_id}")
    finally:
        sz.close()


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
    """Depth to water table: topography - watertable_elevation, clipped >= 0."""
    wt = store.query_field(sim_id, "watertable_elevation", timestep)
    top = _get_topography(store, sim_id)
    return np.maximum(top - wt, 0.0)


def _seepage_mask(store: Any, sim_id: str, timestep: int) -> np.ndarray:
    """Binary seepage indicator for one timestep."""
    top = _get_topography(store, sim_id)
    excess = _surface_excess(store, sim_id, timestep, top.size)
    if excess is not None:
        return seepage_mask(surface_excess=excess)
    sz = store.open_zarr(sim_id)
    try:
        warn_on_geometric_seepage_fallback(sz.root, sim_id=sim_id)
    finally:
        sz.close()
    wt = store.query_field(sim_id, "watertable_elevation", timestep)
    return seepage_mask(watertable=wt, topography=top)


def _surface_excess(
    store: Any,
    sim_id: str,
    timestep: int,
    n_cells: int,
) -> np.ndarray | None:
    """Return the ``budget/surface_excess`` slice, or ``None`` when absent.

    Solvers that do not write that field (MODFLOW 6, MODFLOW-NWT) leave the
    caller with the geometric criterion.
    """
    sz = store.open_zarr(sim_id)
    try:
        budget = sz.root.get("budget")
        if budget is None or "surface_excess" not in budget:
            return None
        values = np.asarray(budget["surface_excess"][timestep], dtype="float64")
        return values.reshape(-1)[:n_cells]
    finally:
        sz.close()


def _drn_budget_field(store: Any, sim_id: str, timestep: int) -> np.ndarray:
    """Read raw DRN budget spatial field, raise KeyError if absent."""
    sz = store.open_zarr(sim_id)
    try:
        budget = sz.root.get("budget")
        if budget is None:
            raise KeyError("No budget spatial fields stored - enable budget.spatial_fields")
        key = find_drain_budget_key(budget)
        if key is not None:
            return np.asarray(budget[key][timestep], dtype="float64")
        raise KeyError("No drain budget field (DRN/DRAINS) in store")
    finally:
        sz.close()


def _outflow_drain(store: Any, sim_id: str, timestep: int) -> np.ndarray:
    """Positive per-cell drain outflow summed over layers."""
    drn = _drn_budget_field(store, sim_id, timestep)
    n_cells = None
    try:
        head = store.query_field(sim_id, "head", timestep)
    except Exception:
        head = None
    if head is not None:
        n_cells = int(np.asarray(head).shape[-1])
    return drain_budget_to_positive_outflow(drn, n_cells=n_cells)


# Registry: variable name -> computation function(store, sim_id, timestep)
# Only cheap derivations belong here.  accumulation_flux requires whitebox D8
# routing and must be pre-computed in the derive phase (see derived.py).
VIRTUAL_FIELDS: dict[str, Any] = {
    "watertable_elevation": _watertable_elevation,
    "watertable_depth": _watertable_depth,
    "seepage_mask": _seepage_mask,
    "outflow_drain": _outflow_drain,
}

# Virtual fields derivable from the persisted head alone (plus mesh topography).
# They are "available" whenever head is stored, even though results.derived.* is
# off by default, so figures find them without a persisted derived group.
# ``outflow_drain`` is excluded: it needs the per-cell drain budget field.
HEAD_DERIVED_VIRTUAL_FIELDS: frozenset[str] = frozenset(
    {"watertable_elevation", "watertable_depth", "seepage_mask"}
)


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


def available_virtual_fields(root: Any) -> list[str]:
    """Virtual fields this store can rebuild, given what it persisted.

    Single source of truth for "is this field readable without a persisted
    derived group", so ``has_field``, ``list_fields`` and the readers cannot
    disagree. The water table needs the stored head, the depth and the
    seepage mask additionally need a surface elevation, and the drain
    outflow needs the per-cell drain budget.
    """
    names: list[str] = []
    if "head" in root:
        names.append("watertable_elevation")
        mesh = root.get("mesh")
        if mesh is not None and ("topography" in mesh or "z_interfaces" in mesh):
            names.extend(("watertable_depth", "seepage_mask"))
    budget = root.get("budget")
    if budget is not None and find_drain_budget_key(budget) is not None:
        names.append("outflow_drain")
    return sorted(names)


def read_field_or_virtual(
    source: Any,
    sim_id: str,
    variable: str,
    timestep: int,
    layer: int | None = None,
) -> np.ndarray:
    """Read one timestep from the store, falling back to a virtual derivation.

    ``source`` implements the catalog reader pair (``open_zarr`` and
    ``query_field``). Raises ``KeyError`` when the variable is neither
    persisted nor derivable.
    """
    sz = source.open_zarr(sim_id)
    try:
        return sz.read_field(variable, timestep, layer=layer)
    except KeyError:
        result = compute_virtual_field(source, str(sim_id), variable, timestep)
        if result is None:
            raise KeyError(f"Variable '{variable}' not found for sim={sim_id}") from None
        if layer is not None and result.ndim == 2:
            return result[layer]
        return result
    finally:
        sz.close()


class _BorrowedZarr:
    """Non-owning view of an open :class:`SimulationZarr`; ``close`` is a no-op."""

    def __init__(self, handle: Any) -> None:
        self._handle = handle

    @property
    def root(self) -> Any:
        return self._handle.root

    def read_field(self, variable: str, timestep: int, *, layer: int | None = None) -> np.ndarray:
        return self._handle.read_field(variable, timestep, layer=layer)

    def close(self) -> None:
        return None


class ZarrFieldSource:
    """Catalog-shaped field reader over one already-open simulation Zarr.

    Exporters hold a store path rather than a catalog, but the virtual
    derivations need the ``open_zarr`` / ``query_field`` pair. Wrapping the
    open handle here lets them resolve derived fields through the same code
    the catalog uses, so an export sees exactly what a read sees.
    """

    def __init__(self, handle: Any, sim_id: str) -> None:
        self._borrowed = _BorrowedZarr(handle)
        self._sim_id = str(sim_id)

    def open_zarr(self, sim_id: str | None = None) -> _BorrowedZarr:
        return self._borrowed

    def query_field(
        self,
        sim_id: str,
        variable: str,
        timestep: int,
        layer: int | None = None,
    ) -> np.ndarray:
        return read_field_or_virtual(self, self._sim_id, variable, timestep, layer=layer)


def derive_field_slice(
    handle: Any,
    sim_id: str,
    variable: str,
    timestep: int,
    layer: int | None = None,
) -> np.ndarray | None:
    """Rebuild one timestep of ``variable`` from an open Zarr handle, or None."""
    if variable not in available_virtual_fields(handle.root):
        return None
    source = ZarrFieldSource(handle, sim_id)
    return source.query_field(sim_id, variable, timestep, layer=layer)


def derive_field_stack(
    handle: Any,
    sim_id: str,
    variable: str,
    timesteps: Sequence[int],
) -> np.ndarray | None:
    """Rebuild ``variable`` over ``timesteps`` from an open Zarr handle, or None."""
    if variable not in available_virtual_fields(handle.root):
        return None
    source = ZarrFieldSource(handle, sim_id)
    return np.stack([np.asarray(source.query_field(sim_id, variable, int(t))) for t in timesteps])
