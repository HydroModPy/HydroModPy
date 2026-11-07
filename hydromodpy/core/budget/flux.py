"""Per-cell budget fluxes: their sign, the drain and release terms, the seepage mask.

A per-cell budget flux has one sign for every solver, the one MODFLOW gives it:
positive when water enters the aquifer, negative when it leaves. Each solver
writes that sign, so a reader never guesses it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.core.scope import CATCHMENT, DOMAIN

logger = get_logger(__name__)

# Canonical public name of the drain budget field. Both MODFLOW backends
# normalize their record name (DRN / DRAINS) through
# ``solver.modflow_common.budget_components.canonical_budget_component``
# before writing, so the store only ever holds "drain".
DRAIN_BUDGET_KEYS = ("drain",)


def select_budget_zone(frame: Any) -> tuple[Any, str]:
    """Return the budget rows of one zone, and the frame they cover.

    A budget table may hold a model-domain row (zone :data:`DOMAIN`) and a
    catchment row (zone :data:`CATCHMENT`) for the same component and timestep.
    The zone whose support is the delineated catchment is written by the solver
    extractors and read by
    ``results.derive.catchment_aggregation``. On a mesh that
    takes in a buffer, a domain row carries the neighboring basins too. The
    catchment lies inside the domain, so summing the two counts its water twice.
    The catchment rows
    are returned when they exist, since every catchment series and the
    hydrograph read them; otherwise the domain rows, otherwise the table as it
    is.
    """
    if "zone_id" not in frame.columns:
        return frame, "the model domain"
    zone_id = frame["zone_id"].astype(str)
    catchment = frame.loc[zone_id == CATCHMENT]
    if not catchment.empty:
        return catchment, "the delineated catchment"
    domain = frame.loc[zone_id == DOMAIN]
    if not domain.empty:
        return domain, "the model domain"
    return frame, "the model domain"


def networks_route_drainage(flow: Any) -> bool:
    """Return whether a stream network takes the hillslope drainage of this flow.

    Only an active SFR network can: ``route_drainage``, on by default, hands the
    outflow of a drain to its reaches through the mover. A lake alone takes none,
    so without a network, or with a network that keeps its drainage out, the
    catchment drains hold water the routed series does not. A published discharge
    and the discharge of a trial both read this answer.
    """
    active = {str(name).lower() for name in getattr(flow, "active_bc", None) or ()}
    sinks_sources = getattr(flow, "sinks_sources", None)
    networks = sinks_sources.get("sfr") if isinstance(sinks_sources, Mapping) else None
    if "sfr" not in active or not networks:
        return False
    for payload in networks.values():
        flag = (
            payload.get("route_drainage")
            if isinstance(payload, Mapping)
            else getattr(payload, "route_drainage", None)
        )
        if flag is False:
            return False
    return True


def find_drain_budget_key(mapping: Any) -> str | None:
    """Return the first stored drain-budget key found in a mapping/group."""
    for key in DRAIN_BUDGET_KEYS:
        try:
            if key in mapping:
                return key
        except TypeError:
            return None
    return None


def _outflow_from_signed(signed: np.ndarray) -> np.ndarray:
    """Sum signed ``(time, layer, cell)`` budgets into positive per-cell outflow.

    Water leaves where the flux is negative. A positive flux enters and adds
    nothing to the outflow, and a missing value counts as no flow.
    """
    finite = np.isfinite(signed) & (signed > -9000.0)
    outflow = np.where(finite, np.maximum(-signed, 0.0), 0.0)
    return outflow.sum(axis=1).astype("float64", copy=False)


def budget_outflow(component_field: Any, *, n_cells: int | None = None) -> np.ndarray:
    """Return the positive per-cell outflow of one step of a signed budget field."""
    field = np.asarray(component_field, dtype=float)
    if field.ndim == 0:
        field = field.reshape(1)

    n_cells_int = int(n_cells or 0)
    if n_cells_int > 0 and field.size % n_cells_int == 0:
        signed = field.reshape(-1, n_cells_int)
    elif field.ndim == 1:
        signed = field.reshape(1, field.size)
    elif field.ndim == 2:
        signed = field
    else:
        signed = field.reshape(field.shape[0], -1)

    return _outflow_from_signed(signed[None])[0]


def budget_outflow_stack(component_stack: Any, *, n_cells: int) -> np.ndarray:
    """Return the positive per-cell outflow of a signed ``(time, ...)`` budget stack.

    Returns a ``(time, n_cells)`` array; layers are summed per timestep.
    """
    stack = np.asarray(component_stack, dtype=float)
    if stack.ndim == 2:
        stack = stack[:, None, :]
    elif stack.ndim != 3:
        raise ValueError(f"Expected a (time, ...) budget stack, got shape {stack.shape}")
    n_cells_int = int(n_cells)
    if stack.size == 0:
        return np.zeros((stack.shape[0], n_cells_int), dtype="float64")
    per_step = stack.shape[1] * stack.shape[2]
    if n_cells_int > 0 and per_step % n_cells_int == 0:
        stack = stack.reshape(stack.shape[0], -1, n_cells_int)
    return _outflow_from_signed(stack)


# Canonical public name of the DRN-TO-MVR budget record (see
# solver.modflow_common.budget_components.canonical_budget_component).
DRN_TO_MVR_KEYS = ("drain_to_mover",)

#: Budget component holding the constant-head flux of the cells that carry the
#: stream role, and only those. MODFLOW 6 places the ocean, the stream and the
#: lateral boundaries in one CHD package, so the ``constant_head`` component
#: alone cannot tell a stream from a model edge. The extractor writes this one
#: from the role sidecar the build left beside the deck
#: (``solver.modflow_common.boundary_roles``), the same mask the calibration
#: criterion reads.
STREAM_CONSTANT_HEAD_BUDGET = "constant_head_stream"

#: Persisted budget components that carry groundwater OUT of the aquifer to the
#: surface, beside the drain: the stream (SFR), the lake (LAK), the stream-role
#: constant head and the Boussinesq ``surface_excess``.
SURFACE_RELEASE_BUDGETS: tuple[str, ...] = (
    "stream",
    "lake",
    STREAM_CONSTANT_HEAD_BUDGET,
    "surface_excess",
)


RELEASE_BUDGET_KEYS: tuple[str, ...] = (
    *DRAIN_BUDGET_KEYS,
    *DRN_TO_MVR_KEYS,
    *SURFACE_RELEASE_BUDGETS,
)
"""Every per-cell budget term :func:`release_flux_stack` reads."""


def drain_stack_with_mover(budget: Any, drn_key: str | None, start: int, stop: int) -> Any:
    """DRN budget rows ``[start, stop)`` summed with the DRN-TO-MVR record.

    With ``route_drainage``, the in-watershed drain flux lives in the DRN-TO-MVR
    record, not the plain DRN one, so the derived spatial fields must include
    both to show catchment drainage rather than only the buffer. Both records
    share one sign convention. Returns None when neither record is present.
    """
    stacks: list[np.ndarray] = []
    if drn_key is not None:
        stacks.append(np.asarray(budget[drn_key][start:stop], dtype="float64"))
    for mvr_key in DRN_TO_MVR_KEYS:
        if mvr_key in budget:
            stacks.append(np.asarray(budget[mvr_key][start:stop], dtype="float64"))
            break
    if not stacks:
        return None
    base = stacks[0]
    for extra in stacks[1:]:
        if extra.shape == base.shape:
            base = base + extra
    return base


def has_release_budget(budget: Any) -> bool:
    """Say whether a budget group holds a path the release flux is built from."""
    if find_drain_budget_key(budget) is not None:
        return True
    return any(name in budget for name in SURFACE_RELEASE_BUDGETS)


def release_flux_stack(budget: Any, *, n_cells: int, start: int, stop: int) -> np.ndarray:
    """Sum every path groundwater takes out of the aquifer, rows ``[start, stop)``.

    Every path, not the drain alone. A run whose streams are in SFR sends most
    of its water through the stream package: measured on the Nancon, 1.3276 of
    the 2.1018 m3/s left through ``stream`` and 0.7986 through ``drain``, and a
    ``release_flux`` holding the drain alone reported dry land over 63 per cent
    of the outgoing water, exactly where a stream-network criterion aims.

    This union is the one the calibration criterion reads off the binary
    budget (``solver.modflow_common.observable_extraction.release_packages_for_model``):
    the drain and DRN-TO-MVR, ``stream`` (SFR), ``lake`` (LAK) and the
    constant head of the stream-role cells (``constant_head_stream``), plus the
    Boussinesq ``surface_excess``, the only path out of that solver. The plain
    ``constant_head`` component carries no role, so it stays out: it would
    count an ocean or a lateral boundary as groundwater released to the
    surface. A run stored before ``constant_head_stream`` existed lacks its
    stream-role constant head here, and only that.

    Every step is computed on its own rows only, so a slice of the result is
    the result over that slice. The stack is non-negative and finite, in the
    m3/s of the budget terms.

    Raises
    ------
    KeyError
        The group holds no release path at all.
    """
    drn_key = find_drain_budget_key(budget)
    extra = [name for name in SURFACE_RELEASE_BUDGETS if name in budget]
    if drn_key is None and not extra:
        raise KeyError(
            "No release budget field: expected a drain component or one of "
            f"{sorted(SURFACE_RELEASE_BUDGETS)}."
        )
    n_steps = int(stop) - int(start)
    if n_steps <= 0:
        return np.empty((0, int(n_cells)), dtype="float64")
    release = np.zeros((n_steps, int(n_cells)), dtype="float64")
    drn_stack = drain_stack_with_mover(budget, drn_key, int(start), int(stop))
    if drn_stack is not None:
        release += budget_outflow_stack(drn_stack, n_cells=n_cells)
    for name in extra:
        stack = np.asarray(budget[name][int(start) : int(stop)], dtype="float64")
        release += budget_outflow_stack(stack, n_cells=n_cells)
    return release


def seepage_mask(
    *,
    watertable: Any | None = None,
    topography: Any | None = None,
    surface_excess: Any | None = None,
    band_depth: float = 0.0,
) -> np.ndarray:
    """Canonical seepage criterion, shared by every reader and writer.

    ``surface_excess`` is the solver-declared surface release flux, negative
    where water leaves the aquifer like every budget flux. When a backend
    produces it (Boussinesq constrained formulations) it wins: those formulations
    clamp the head at the surface over broad areas while the real seepage flows
    through that flux, so the geometric test over-reports. Without it (MODFLOW 6,
    MODFLOW-NWT) the mask is ``watertable >= topography``.

    ``band_depth`` is the sub-cell discharge band the run gave its drains
    (``solver.drain_band_depth_m``). A banded drain sits at ``top - D/2``, the
    lowest land the cell is declared to hold, so a cell discharges as soon as
    the water table reaches that elevation and never climbs back to ``top``.
    Testing against ``top`` on a banded run therefore returns an all-false mask
    while the drains are discharging: measured on the Nancon, reaching ``top``
    would take four orders of magnitude more flux than the recharge supplies.
    The criterion is ``watertable >= topography - band_depth / 2``, and
    ``band_depth = 0`` is the unbanded test unchanged.

    Accepts a single timestep ``(n_cells,)`` or a stack ``(time, n_cells)`` and
    returns a float mask of the same shape.
    """
    if surface_excess is not None:
        return (np.asarray(surface_excess, dtype=float) < 0.0).astype("float64")
    if watertable is None or topography is None:
        raise ValueError("seepage_mask needs either surface_excess or watertable + topography")
    wt = np.asarray(watertable, dtype=float)
    top = np.asarray(topography, dtype=float).reshape(-1) - 0.5 * float(band_depth)
    if wt.ndim == 2:
        top = top[None, :]
    return (wt >= top).astype("float64")


DRAIN_BAND_DEPTH_ATTR = "drain_band_depth_m"


def drain_band_depth(root: Any) -> float:
    """Read the discharge band a run gave its drains back from its store.

    The band changes what "this cell seeps" means, so every reader of
    :func:`seepage_mask` has to know it, including a figure drawn months after
    the run. It travels in the store rather than through a call chain for the
    same reason the surface-release flux does: the criterion interrogates the
    file, not the object that produced it. Absent, which is every run written
    before the option existed, it reads 0.0 and the criterion is unchanged.
    """
    try:
        value = root.attrs.get(DRAIN_BAND_DEPTH_ATTR)
    except (AttributeError, TypeError):
        return 0.0
    if value is None:
        return 0.0
    depth = float(value)
    return depth if np.isfinite(depth) and depth > 0.0 else 0.0


# Zarr group the Boussinesq adapter writes for every run it extracts. Its
# presence identifies a backend whose seepage is a surface-release flux, so a
# store holding it but no ``budget/surface_excess`` lost that signal.
SURFACE_EXCESS_STATE_GROUP = "boussinesq_state"


def warn_on_geometric_seepage_fallback(root: Any, *, sim_id: str) -> None:
    """Warn when a surface-excess run falls back to the geometric criterion.

    Call it right before building a seepage mask without ``surface_excess``.
    On MODFLOW backends the geometric test is the criterion and nothing is
    logged; on a solver that releases water through a flux it is a physics
    degradation the user must see.
    """
    try:
        degraded = SURFACE_EXCESS_STATE_GROUP in root
    except TypeError:
        return
    if not degraded:
        return
    from hydromodpy.core.budget.terms import POLICY_ALL, kept_budget

    kept = kept_budget(root)
    if kept is None:
        cause = "This run was written before the per-cell budget was kept by default: run it again."
    elif kept.policy == POLICY_ALL:
        cause = "The solver produced no surface excess for this run: there is no option to set."
    else:
        cause = (
            f"This run kept only the per-cell budget terms its consumers read "
            f"({', '.join(kept.terms) or 'none'}); "
            "[simulation.results] keep_per_cell_budget = true keeps surface_excess."
        )
    logger.warning(
        "Seepage mask for sim %s falls back to the geometric criterion "
        "(water table >= surface): this solver releases seepage through "
        "budget/surface_excess, which the store does not hold, so the mask "
        "over-reports the seepage extent. %s",
        sim_id,
        cause,
    )


__all__ = [
    "DRAIN_BAND_DEPTH_ATTR",
    "DRAIN_BUDGET_KEYS",
    "DRN_TO_MVR_KEYS",
    "RELEASE_BUDGET_KEYS",
    "STREAM_CONSTANT_HEAD_BUDGET",
    "SURFACE_RELEASE_BUDGETS",
    "budget_outflow",
    "budget_outflow_stack",
    "drain_band_depth",
    "drain_stack_with_mover",
    "find_drain_budget_key",
    "has_release_budget",
    "release_flux_stack",
    "seepage_mask",
]
