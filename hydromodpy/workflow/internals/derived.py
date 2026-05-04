"""Derived-field registry for the pipeline ``derive`` step.

Derived fields (watertable elevation/depth, seepage mask, cell-averaged
fluxes) are computed from primary solver outputs already persisted in the
Zarr store (``head``, ``budget``, ``mesh``). This module exposes:

- :class:`DerivedComputation` - a ``Protocol`` that any derivation must
  implement. A computation declares its output name, its required input
  fields, an optional set of upstream derivations, and a ``compute``
  method.
- :class:`DerivedRegistry` - an ordered registry of computations with
  ``register``, ``get``, ``list``, and an ``apply`` helper that honours
  topological order and skips entries whose inputs are missing.
- :data:`registry` - the module-level singleton pre-populated with the
  canonical derivations (watertable elevation/depth, seepage mask,
  cell-averaged fluxes).

Heavy solver-specific post-processing (flopy multilayer water-table,
whitebox drain routing) stays in
:mod:`hydromodpy.simulation.extraction.extractors.derived`. This registry
provides the portable, pure-Python derivations that the canonical
``DeriveStep`` consumes; the two paths cooperate without duplicating.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.results import derived as _pure
from hydromodpy.results.zarr_store import SimulationZarr

logger = get_logger(__name__)

__all__ = (
    "DerivedComputation",
    "DerivedRegistry",
    "DerivedResult",
    "registry",
)


@dataclass(frozen=True)
class DerivedResult:
    """Outcome of a single derived computation run."""

    name: str
    status: str  # "computed" | "skipped"
    reason: str = ""


@runtime_checkable
class DerivedComputation(Protocol):
    """Contract for a derived-field computation.

    A computation is a small object that knows its output name, the inputs
    it needs inside the Zarr store, optionally the upstream derivations it
    depends on (for topological ordering), and how to compute itself on a
    :class:`~hydromodpy.results.zarr_store.SimulationZarr`.
    """

    name: str
    required_inputs: tuple[str, ...]
    required_derived: tuple[str, ...]
    description: str

    def compute(self, sim_zarr: SimulationZarr, **ctx: Any) -> DerivedResult:
        """Compute the derivation and write it into ``sim_zarr``.

        Implementations must return a :class:`DerivedResult` that signals
        whether the derivation ran (``"computed"``) or was skipped
        (``"skipped"``) along with a short reason.
        """
        ...


# ---------------------------------------------------------------------------
# Helpers for locating inputs inside a simulation Zarr store.
# ---------------------------------------------------------------------------


def _root_has(sim_zarr: SimulationZarr, name: str) -> bool:
    return name in sim_zarr.root


def _subgroup_has(sim_zarr: SimulationZarr, subgroup: str, name: str) -> bool:
    group = sim_zarr.root.get(subgroup)
    return group is not None and name in group


def _surface_top(sim_zarr: SimulationZarr, n_cells: int) -> np.ndarray | None:
    mesh = sim_zarr.root.get("mesh")
    if mesh is None:
        return None
    if "surface_top" in mesh:
        return np.asarray(mesh["surface_top"][:], dtype="float64").ravel()[:n_cells]
    if "z_interfaces" in mesh:
        z_intf = np.asarray(mesh["z_interfaces"][:], dtype="float64")
        if z_intf.size == 0:
            return None
        return np.full(n_cells, float(z_intf[0]))
    return None


def _cell_area(sim_zarr: SimulationZarr, n_cells: int) -> np.ndarray | None:
    mesh = sim_zarr.root.get("mesh")
    if mesh is None:
        return None
    if "cell_area" in mesh:
        return np.asarray(mesh["cell_area"][:], dtype="float64").ravel()[:n_cells]
    return None


def _head_shape(sim_zarr: SimulationZarr) -> tuple[int, int, int]:
    head = sim_zarr.root["head"]
    shape = tuple(int(s) for s in head.shape)
    if len(shape) == 2:
        n_timesteps, n_cells = shape
        n_layers = 1
    else:
        n_timesteps, n_layers, n_cells = shape
    return n_timesteps, n_layers, n_cells


def _write_derived(
    sim_zarr: SimulationZarr,
    variable: str,
    timestep: int,
    values: np.ndarray,
    *,
    n_timesteps: int | None,
) -> None:
    sim_zarr.write_field(
        variable,
        timestep,
        values,
        n_timesteps=n_timesteps,
        subgroup="derived",
    )


# ---------------------------------------------------------------------------
# Concrete computations.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Computation:
    """Lightweight :class:`DerivedComputation` backed by a callable."""

    name: str
    required_inputs: tuple[str, ...]
    required_derived: tuple[str, ...]
    description: str
    func: Callable[[SimulationZarr], DerivedResult]

    def compute(self, sim_zarr: SimulationZarr, **ctx: Any) -> DerivedResult:
        return self.func(sim_zarr)


def _run_watertable_elevation(sim_zarr: SimulationZarr) -> DerivedResult:
    n_timesteps, n_layers, n_cells = _head_shape(sim_zarr)
    top = _surface_top(sim_zarr, n_cells)
    if top is None:
        return DerivedResult(
            name="watertable_elevation",
            status="skipped",
            reason="mesh surface elevation unavailable",
        )
    head_arr = sim_zarr.root["head"]
    for t in range(n_timesteps):
        head_t = np.asarray(head_arr[t], dtype="float64")
        if head_t.ndim == 2:
            head_t = head_t.reshape(n_layers, n_cells)
        wt = _pure.watertable_elevation(head_t, top)
        wt = np.asarray(wt, dtype="float64").ravel()[:n_cells]
        _write_derived(
            sim_zarr,
            "watertable_elevation",
            t,
            wt,
            n_timesteps=n_timesteps if t == 0 else None,
        )
    return DerivedResult(name="watertable_elevation", status="computed")


def _run_watertable_depth(sim_zarr: SimulationZarr) -> DerivedResult:
    n_timesteps, _n_layers, n_cells = _head_shape(sim_zarr)
    top = _surface_top(sim_zarr, n_cells)
    if top is None:
        return DerivedResult(
            name="watertable_depth",
            status="skipped",
            reason="mesh surface elevation unavailable",
        )
    derived_grp = sim_zarr.root.get("derived")
    if derived_grp is None or "watertable_elevation" not in derived_grp:
        return DerivedResult(
            name="watertable_depth",
            status="skipped",
            reason="watertable_elevation missing",
        )
    wt_arr = derived_grp["watertable_elevation"]
    for t in range(n_timesteps):
        wt = np.asarray(wt_arr[t], dtype="float64").ravel()[:n_cells]
        depth = np.maximum(top - wt, 0.0)
        _write_derived(
            sim_zarr,
            "watertable_depth",
            t,
            depth,
            n_timesteps=n_timesteps if t == 0 else None,
        )
    return DerivedResult(name="watertable_depth", status="computed")


def _run_seepage_mask(sim_zarr: SimulationZarr) -> DerivedResult:
    n_timesteps, _n_layers, n_cells = _head_shape(sim_zarr)
    top = _surface_top(sim_zarr, n_cells)
    if top is None:
        return DerivedResult(
            name="seepage_mask",
            status="skipped",
            reason="mesh surface elevation unavailable",
        )
    derived_grp = sim_zarr.root.get("derived")
    if derived_grp is None or "watertable_elevation" not in derived_grp:
        return DerivedResult(
            name="seepage_mask",
            status="skipped",
            reason="watertable_elevation missing",
        )
    wt_arr = derived_grp["watertable_elevation"]
    for t in range(n_timesteps):
        wt = np.asarray(wt_arr[t], dtype="float64").ravel()[:n_cells]
        surface_excess_mask = _surface_excess_seepage_mask(sim_zarr, t, n_cells)
        if surface_excess_mask is not None:
            mask = surface_excess_mask
        else:
            mask = wt >= top
        _write_derived(
            sim_zarr,
            "seepage_mask",
            t,
            mask.astype("float64"),
            n_timesteps=n_timesteps if t == 0 else None,
        )
    return DerivedResult(name="seepage_mask", status="computed")


def _surface_excess_seepage_mask(
    sim_zarr: SimulationZarr,
    timestep: int,
    n_cells: int,
) -> np.ndarray | None:
    """Return seepage cells declared by solver surface-excess fields.

    Authoritative when present: Boussinesq constrained formulations expose
    active seepage through their solver-produced surface-excess flux (or
    a pre-computed ``derived/seepage_rate``). Returns ``None`` for solvers
    that do not write these fields (MODFLOW 6, MODFLOW-NWT); the caller
    then derives the mask from the geometric head/topography criterion.
    """
    derived_grp = sim_zarr.root.get("derived")
    if derived_grp is not None and "seepage_rate" in derived_grp:
        rate = np.asarray(derived_grp["seepage_rate"][timestep], dtype="float64")
        return np.asarray(rate).reshape(-1)[:n_cells] > 0.0

    budget_grp = sim_zarr.root.get("budget")
    if budget_grp is not None and "surface_excess" in budget_grp:
        flux = np.asarray(budget_grp["surface_excess"][timestep], dtype="float64")
        return np.asarray(flux).reshape(-1)[:n_cells] > 0.0

    return None


def _run_fluxes_from_budget(sim_zarr: SimulationZarr) -> DerivedResult:
    budget_grp = sim_zarr.root.get("budget")
    if budget_grp is None or len(list(budget_grp.array_keys())) == 0:
        return DerivedResult(
            name="fluxes_from_budget",
            status="skipped",
            reason="no budget fields available",
        )
    n_timesteps, _n_layers, n_cells = _head_shape(sim_zarr)
    area = _cell_area(sim_zarr, n_cells)
    if area is None:
        return DerivedResult(
            name="fluxes_from_budget",
            status="skipped",
            reason="mesh/cell_area unavailable",
        )
    # Pick the first scalar-like budget component available (the pure
    # helper operates component-by-component). Most simulations record a
    # drain/recharge component; leave others untouched.
    component_name: str | None = None
    for candidate in ("drn", "rch", "recharge", "drain", "drains"):
        if candidate in budget_grp:
            component_name = candidate
            break
    if component_name is None:
        return DerivedResult(
            name="fluxes_from_budget",
            status="skipped",
            reason="no known budget component to normalise",
        )
    comp_arr = budget_grp[component_name]
    for t in range(n_timesteps):
        field = np.asarray(comp_arr[t], dtype="float64")
        if field.ndim == 2:
            field = field.sum(axis=0)
        field = field.ravel()[:n_cells]
        flux = _pure.fluxes_from_budget(field, area)
        flux = np.asarray(flux, dtype="float64").ravel()[:n_cells]
        _write_derived(
            sim_zarr,
            "fluxes_from_budget",
            t,
            flux,
            n_timesteps=n_timesteps if t == 0 else None,
        )
    return DerivedResult(name="fluxes_from_budget", status="computed")


# ---------------------------------------------------------------------------
# Registry.
# ---------------------------------------------------------------------------


@dataclass
class DerivedRegistry:
    """Ordered registry of :class:`DerivedComputation` objects.

    Entries are stored in insertion order; :meth:`ordered_names` returns a
    topological order that respects ``required_derived`` dependencies.
    """

    _entries: dict[str, DerivedComputation] = field(default_factory=dict)

    def register(self, comp: DerivedComputation, *, overwrite: bool = False) -> None:
        if comp.name in self._entries and not overwrite:
            raise ConfigError(f"DerivedComputation '{comp.name}' already registered")
        self._entries[comp.name] = comp

    def get(self, name: str) -> DerivedComputation:
        return self._entries[name]

    def list(self) -> tuple[str, ...]:  # noqa: A003 - mirrors public API
        return tuple(self._entries.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def ordered_names(self) -> tuple[str, ...]:
        """Return registered names in a dependency-respecting order.

        Falls back to insertion order for independent entries and raises
        :class:`ConfigError` if a cycle is detected.
        """
        resolved: list[str] = []
        seen: set[str] = set()
        temp: set[str] = set()

        def visit(name: str) -> None:
            if name in seen:
                return
            if name in temp:
                raise ConfigError(f"Cycle in derived registry at '{name}'")
            temp.add(name)
            comp = self._entries[name]
            for dep in comp.required_derived:
                if dep in self._entries:
                    visit(dep)
            temp.discard(name)
            seen.add(name)
            resolved.append(name)

        for key in self._entries:
            visit(key)
        return tuple(resolved)

    def apply(
        self,
        sim_zarr: SimulationZarr,
        *,
        names: Iterable[str] | None = None,
        **ctx: Any,
    ) -> tuple[DerivedResult, ...]:
        """Run registered derivations in topological order.

        Parameters
        ----------
        sim_zarr
            Target simulation Zarr store; derivations write to ``/derived``.
        names
            Optional subset of derivation names to run. Unknown names raise
            ``KeyError``.
        ctx
            Forwarded to each computation's ``compute`` method.
        """
        ordered = self.ordered_names()
        wanted = set(ordered if names is None else names)
        for name in wanted:
            if name not in self._entries:
                raise KeyError(f"Unknown derived computation '{name}'")

        results: list[DerivedResult] = []
        for name in ordered:
            if name not in wanted:
                continue
            comp = self._entries[name]
            for required in comp.required_inputs:
                if not (
                    _root_has(sim_zarr, required)
                    or _subgroup_has(sim_zarr, "budget", required)
                    or _subgroup_has(sim_zarr, "mesh", required)
                    or _subgroup_has(sim_zarr, "derived", required)
                ):
                    reason = f"input '{required}' missing"
                    logger.debug("DerivedRegistry: skipping '%s' (%s)", name, reason)
                    results.append(DerivedResult(name=name, status="skipped", reason=reason))
                    break
            else:
                try:
                    result = comp.compute(sim_zarr, **ctx)
                except Exception as exc:  # pragma: no cover - logged + surfaced
                    logger.warning("DerivedRegistry: '%s' raised %s", name, exc)
                    results.append(
                        DerivedResult(name=name, status="skipped", reason=f"error: {exc}")
                    )
                    continue
                logger.debug(
                    "DerivedRegistry: '%s' -> %s (%s)",
                    name,
                    result.status,
                    result.reason or "ok",
                )
                results.append(result)
        return tuple(results)


def _build_default_registry() -> DerivedRegistry:
    reg = DerivedRegistry()
    reg.register(
        _Computation(
            name="watertable_elevation",
            required_inputs=("head",),
            required_derived=(),
            description="Head clipped to the mesh surface elevation.",
            func=_run_watertable_elevation,
        )
    )
    reg.register(
        _Computation(
            name="watertable_depth",
            required_inputs=("head",),
            required_derived=("watertable_elevation",),
            description="Distance from mesh surface down to the water table.",
            func=_run_watertable_depth,
        )
    )
    reg.register(
        _Computation(
            name="seepage_mask",
            required_inputs=("head",),
            required_derived=("watertable_elevation",),
            description="Boolean mask where the water table reaches the surface.",
            func=_run_seepage_mask,
        )
    )
    reg.register(
        _Computation(
            name="fluxes_from_budget",
            required_inputs=("head",),
            required_derived=(),
            description="Per-cell flux (m/d) derived from a budget component.",
            func=_run_fluxes_from_budget,
        )
    )
    return reg


registry: DerivedRegistry = _build_default_registry()
