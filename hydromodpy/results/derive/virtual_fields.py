"""On-the-fly derived fields computed from stored primary variables.

The store only persists primary variables: the head, the budget terms, the
concentration and the mesh. Every derived field is rebuilt on read from them:
``watertable_elevation``, ``watertable_depth``, ``seepage_mask``,
``outflow_drain``, ``release_flux``, ``fluxes_from_budget``, the two
accumulation fluxes and the solute chain ``concentration_seepage``,
``mass_seepage``, ``mass_accumulated``. Each has a whole-range computation in
:data:`VIRTUAL_FIELD_ROWS`, and a single step is one row of it, so a step read
alone equals the row of a range read, bit for bit. A store written before the
fields were rebuilt on read may still hold some of them under ``derived/``:
every reader tries the stored array first, and a rebuilt field reads an
upstream field stored first too.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.budget_terms import POLICY_CONSUMERS, budget_terms_for, kept_budget
from hydromodpy.core.field_routing import (
    DRN_TO_MVR_KEYS,
    drain_band_depth,
    drain_budget_stack_to_positive_outflow,
    drain_stack_with_mover,
    find_drain_budget_key,
    has_release_budget,
    release_flux_stack,
    seepage_mask,
    warn_on_geometric_seepage_fallback,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.results import field_registry
from hydromodpy.results.derive.accumulation import (
    accumulation_flux_available,
    accumulation_flux_rows,
    release_accumulation_flux_available,
    release_accumulation_flux_rows,
)
from hydromodpy.results.field_registry import SHAPE_TIME_FACE, FieldDescriptor
from hydromodpy.results.zarr_store.zarr_reader import step_range_bounds

logger = get_logger(__name__)

RowsOf = Callable[[int, int], np.ndarray]
"""Rows ``[first, last)`` of a field, once its inputs are resolved."""


def _cell_count(root: Any, fallback: Any = None) -> int:
    """Number of cells along the face axis of the head, else of the concentration."""
    for name in ("head", "concentration"):
        if name in root:
            return int(root[name].shape[-1])
    if fallback is not None:
        return int(fallback.shape[-1])
    raise KeyError("The store holds neither a head nor a concentration to size the field on")


def _time_axis_length(root: Any) -> int | None:
    """Number of steps of the head, else of the concentration; None when the store has neither."""
    for name in ("head", "concentration"):
        if name in root:
            return int(root[name].shape[0])
    return None


ROWS_PER_PASS_ELEMENTS = 2_000_000
"""Steps times cells a whole-range rebuild computes in one pass (16 MB in float64)."""


def _in_passes(
    compute: RowsOf,
    start: int,
    stop: int,
    n_cells: int,
    *,
    per_cell: int = 1,
) -> np.ndarray:
    """Join ``compute(first, last)`` over ``[start, stop)`` run in bounded passes.

    A pass over a whole daily run allocates temporaries of hundreds of MB and
    runs several times slower than small passes whose memory is reused. Every
    step reads its own rows only, so the joined passes equal one pass.
    ``per_cell`` is the number of values a pass reads per output cell and step
    (the layers of the head), so the pass size follows what is read.
    """
    per_pass = max(1, ROWS_PER_PASS_ELEMENTS // max(1, int(n_cells) * int(per_cell)))
    out = np.empty((max(0, int(stop) - int(start)), int(n_cells)), dtype="float64")
    for first in range(int(start), int(stop), per_pass):
        last = min(first + per_pass, int(stop))
        out[first - int(start) : last - int(start)] = compute(first, last)
    return out


def _one_step(rows: Callable[[Any, int, int], np.ndarray], root: Any, timestep: int) -> np.ndarray:
    """Return step ``timestep`` of a whole-range rebuild; a negative step counts from the end.

    Raises ``IndexError`` when the step is outside the time axis, as a stored
    array does.
    """
    step = int(timestep)
    n_steps = _time_axis_length(root)
    if n_steps is None:
        return rows(root, step, step + 1)[0]
    if step < 0:
        step += n_steps
    first, last = step_range_bounds(step, step + 1, n_steps)
    return rows(root, first, last)[0]


def _has_stored(root: Any, name: str) -> bool:
    """Say whether an older run stored ``name`` under ``derived/``."""
    derived = root.get("derived")
    return derived is not None and name in derived


def _stored_rows(root: Any, name: str) -> RowsOf:
    """Rows of the array an older run stored under ``derived/``, widened to float64."""
    array = root["derived"][name]

    def rows(first: int, last: int) -> np.ndarray:
        stack = np.asarray(array[first:last], dtype="float64")
        return stack.reshape(stack.shape[0], -1)

    return rows


def _stored_or(root: Any, name: str, rebuild: Callable[[], RowsOf]) -> RowsOf:
    """Rows of ``name`` as stored when the run holds it, else as ``rebuild`` makes them."""
    return _stored_rows(root, name) if _has_stored(root, name) else rebuild()


def _run_label(root: Any) -> str:
    """Name of the run folder holding the store, for a log line to point at."""
    path = getattr(getattr(root, "store", None), "root", None)
    return Path(str(path)).parent.name if path is not None else "unknown"


def _surface_elevation(root: Any, n_cells: int) -> np.ndarray:
    """Per-cell surface elevation: the mesh topography, else the first interface everywhere."""
    mesh = root["mesh"]
    if "topography" in mesh:
        return np.asarray(mesh["topography"][:], dtype="float64").reshape(-1)[:n_cells]
    if "z_interfaces" in mesh:
        return np.full(n_cells, float(mesh["z_interfaces"][:][0]), dtype="float64")
    raise KeyError("No surface elevation data in the store")


def _has_surface_elevation(root: Any) -> bool:
    mesh = root.get("mesh")
    return mesh is not None and ("topography" in mesh or "z_interfaces" in mesh)


def _first_finite_layer(head: np.ndarray) -> np.ndarray:
    """Head of the uppermost layer that is finite, per step and cell; NaN when none is."""
    if head.ndim == 2:
        return head
    wt = np.where(np.isfinite(head[:, 0]), head[:, 0], np.nan)
    for layer in range(1, head.shape[1]):
        below = head[:, layer]
        wt = np.where(np.isnan(wt) & np.isfinite(below), below, wt)
    return wt


def _watertable_plan(root: Any) -> RowsOf:
    """Rows of the water table, the stored array first."""
    if _has_stored(root, "watertable_elevation"):
        return _stored_rows(root, "watertable_elevation")
    head = root["head"]

    def rows(first: int, last: int) -> np.ndarray:
        return _first_finite_layer(np.asarray(head[first:last], dtype="float64"))

    return rows


def _head_layers(root: Any) -> int:
    """Number of layers of the stored head, 1 for a flat head or none."""
    head = root.get("head")
    return int(head.shape[1]) if head is not None and head.ndim == 3 else 1


def watertable_elevation_rows(root: Any, start: int, stop: int) -> np.ndarray:
    """Return the water table over steps ``[start, stop)``: head at the uppermost wet layer.

    The head itself, never clipped to the surface. A cell with no finite head
    in any layer is NaN.
    """
    if "head" not in root:
        raise KeyError("No head stored")
    return _in_passes(
        _watertable_plan(root), start, stop, _cell_count(root), per_cell=_head_layers(root)
    )


def watertable_depth_rows(root: Any, start: int, stop: int) -> np.ndarray:
    """Return the depth to the water table, ``max(top - water table, 0)``, over ``[start, stop)``."""
    if "head" not in root:
        raise KeyError("No head stored")
    n_cells = _cell_count(root)
    top = _surface_elevation(root, n_cells)
    water_table = _watertable_plan(root)

    def rows(first: int, last: int) -> np.ndarray:
        return np.maximum(top - water_table(first, last), 0.0)

    return _in_passes(rows, start, stop, n_cells, per_cell=_head_layers(root))


def _has_surface_excess(root: Any) -> bool:
    budget = root.get("budget")
    return budget is not None and "surface_excess" in budget


def _seepage_available(root: Any) -> bool:
    """Say whether a seepage mask can be had: stored, from a surface excess, or geometric."""
    return (
        _has_stored(root, "seepage_mask")
        or _has_surface_excess(root)
        or ("head" in root and _has_surface_elevation(root))
    )


def _seepage_plan(root: Any, n_cells: int) -> RowsOf:
    """Rows of the seepage mask: the solver surface excess, else the geometric criterion.

    The geometric fallback warns once here, when the plan is made, whatever the
    number of passes that follow.
    """
    if _has_surface_excess(root):
        excess = root["budget"]["surface_excess"]

        def from_excess(first: int, last: int) -> np.ndarray:
            values = np.asarray(excess[first:last], dtype="float64")
            return seepage_mask(surface_excess=values.reshape(values.shape[0], -1)[:, :n_cells])

        return from_excess
    if "head" not in root or not _has_surface_elevation(root):
        raise KeyError("seepage_mask needs a surface excess, or a head and a surface elevation")
    warn_on_geometric_seepage_fallback(root, sim_id=_run_label(root))
    top = _surface_elevation(root, n_cells)
    band = drain_band_depth(root)
    water_table = _watertable_plan(root)

    def geometric(first: int, last: int) -> np.ndarray:
        return seepage_mask(watertable=water_table(first, last), topography=top, band_depth=band)

    return geometric


def seepage_mask_rows(root: Any, start: int, stop: int) -> np.ndarray:
    """Return the seepage mask (1 where the cell seeps, else 0) over ``[start, stop)``.

    The solver surface excess decides when the store holds it. Otherwise the
    mask is ``water table >= top - drain band / 2``, and a run that releases its
    seepage through a surface excess logs that it fell back to this test.
    """
    n_cells = _cell_count(root)
    return _in_passes(
        _seepage_plan(root, n_cells), start, stop, n_cells, per_cell=_head_layers(root)
    )


def _has_drain_term(budget: Any) -> bool:
    return find_drain_budget_key(budget) is not None or any(
        key in budget for key in DRN_TO_MVR_KEYS
    )


def outflow_drain_rows(root: Any, start: int, stop: int) -> np.ndarray:
    """Return the positive drain outflow, summed over layers, over steps ``[start, stop)``.

    The drain term with the drain-to-mover term added when the run holds both,
    in the unit of the budget. The sign convention is the one of
    :func:`hydromodpy.core.field_routing.drain_budget_stack_to_positive_outflow`;
    the result is non-negative and finite.
    """
    budget = root.get("budget")
    if budget is None:
        raise KeyError("the run kept no per-cell budget")
    drn_key = find_drain_budget_key(budget)
    if not _has_drain_term(budget):
        raise KeyError("No drain budget field (DRN/DRAINS) in store")
    n_cells = _cell_count(root, budget[drn_key] if drn_key is not None else None)

    def rows(first: int, last: int) -> np.ndarray:
        stack = drain_stack_with_mover(budget, drn_key, first, last)
        outflow = np.maximum(drain_budget_stack_to_positive_outflow(stack, n_cells=n_cells), 0.0)
        return np.where(np.isfinite(outflow), outflow, 0.0)

    return _in_passes(rows, start, stop, n_cells)


def _concentration_seepage_plan(root: Any) -> RowsOf:
    """Rows of the concentration at seepage cells, the stored array first.

    The seepage is the stored mask when the run holds one, else the surface
    excess, else the geometric criterion. Outside the seepage the value is NaN.
    """
    if _has_stored(root, "concentration_seepage"):
        return _stored_rows(root, "concentration_seepage")
    if "concentration" not in root:
        raise KeyError("No concentration stored: concentration_seepage needs a transport run")
    if not _seepage_available(root):
        raise KeyError("concentration_seepage needs a seepage mask")
    concentration = root["concentration"]
    seepage = _stored_or(root, "seepage_mask", lambda: _seepage_plan(root, _cell_count(root)))

    def rows(first: int, last: int) -> np.ndarray:
        conc = np.asarray(concentration[first:last], dtype="float64")
        if conc.ndim == 3:
            conc = conc[:, 0]
        mask = seepage(first, last)
        return np.where(mask > 0, conc * mask, np.nan)

    return rows


def concentration_seepage_rows(root: Any, start: int, stop: int) -> np.ndarray:
    """Return the concentration of the first layer at seepage cells, NaN elsewhere."""
    return _in_passes(
        _concentration_seepage_plan(root),
        start,
        stop,
        _cell_count(root),
        per_cell=_head_layers(root),
    )


def _mass_seepage_plan(root: Any) -> RowsOf:
    """Rows of the solute mass flux at seepage cells, the stored array first.

    The concentration at seepage cells times the positive drain outflow. Only
    the drain term counts here, the drain-to-mover term does not, and a run
    with no drain term multiplies by one.
    """
    if _has_stored(root, "mass_seepage"):
        return _stored_rows(root, "mass_seepage")
    budget = root.get("budget")
    if budget is None:
        raise KeyError("the run kept no per-cell budget")
    concentration_seepage = _concentration_seepage_plan(root)
    n_cells = _cell_count(root)
    drn_key = find_drain_budget_key(budget)

    def rows(first: int, last: int) -> np.ndarray:
        if drn_key is None:
            flux = np.ones((last - first, n_cells), dtype="float64")
        else:
            drain = np.asarray(budget[drn_key][first:last], dtype="float64")
            flux = drain_budget_stack_to_positive_outflow(drain, n_cells=n_cells)
        return concentration_seepage(first, last) * flux

    return rows


def mass_seepage_rows(root: Any, start: int, stop: int) -> np.ndarray:
    """Return the solute mass flux at seepage cells over steps ``[start, stop)``."""
    return _in_passes(
        _mass_seepage_plan(root),
        start,
        stop,
        _cell_count(root),
        per_cell=_head_layers(root),
    )


def mass_accumulated_rows(root: Any, start: int, stop: int) -> np.ndarray:
    """Return the running sum of ``mass_seepage`` over steps ``[start, stop)``.

    The sum runs from step 0, so a range costs the steps before it too. A NaN
    stays NaN from its step on. The passes carry the sum over, adding the
    steps in the order ``np.cumsum`` does, so the rows equal the cumulative
    sum of the whole run, bit for bit.
    """
    mass_seepage = _mass_seepage_plan(root)
    n_cells = _cell_count(root)
    first_row, last_row = int(start), int(stop)
    if last_row <= first_row:
        return np.empty((0, n_cells), dtype="float64")
    out = np.empty((max(0, last_row - first_row), n_cells), dtype="float64")
    per_pass = max(1, ROWS_PER_PASS_ELEMENTS // max(1, n_cells * _head_layers(root)))
    carry: np.ndarray | None = None
    for first in range(0, last_row, per_pass):
        last = min(first + per_pass, last_row)
        block = np.array(mass_seepage(first, last), dtype="float64")
        if carry is not None:
            block[0] += carry
        block = np.cumsum(block, axis=0)
        carry = block[-1]
        kept = max(first, first_row)
        if kept < last:
            out[kept - first_row : last - first_row] = block[kept - first :]
    return out


def release_flux_rows(root: Any, start: int, stop: int) -> np.ndarray:
    """Return ``release_flux`` over steps ``[start, stop)`` from the stored budget.

    The ``(stop - start, n_cells)`` stack is the one the post-run derivation
    used to store (:func:`hydromodpy.core.field_routing.release_flux_stack`),
    step for step: every step reads its own budget rows only.
    """
    budget = root.get("budget")
    if budget is None:
        raise KeyError("the run kept no per-cell budget")
    if not has_release_budget(budget):
        raise KeyError("No release budget field: expected a drain, stream, lake or surface excess")
    n_cells = _cell_count(root)
    return _in_passes(
        lambda first, last: release_flux_stack(budget, n_cells=n_cells, start=first, stop=last),
        start,
        stop,
        n_cells,
    )


FLUX_BUDGET_COMPONENTS = ("drain", "recharge")
"""Budget terms ``fluxes_from_budget`` normalises, the first one present wins."""


def cell_area_from_mesh(root: Any, n_cells: int) -> np.ndarray | None:
    """Per-cell area in m2, computed from the mesh geometry the run persisted.

    A run stores its vertices and its face-node connectivity, never an area
    array. The polygons are the same ones every other reader rebuilds, so the
    areas agree cell for cell with what the solver was given. None when the
    store has no geometry or no cell of positive area.
    """
    from hydromodpy.spatial.mesh.ops.vector_cell_mask import cell_polygons

    mesh = root.get("mesh")
    if mesh is None or "vertices" not in mesh or "face_node_connectivity" not in mesh:
        return None
    polygons = cell_polygons(
        np.asarray(mesh["vertices"][:], dtype="float64"),
        np.asarray(mesh["face_node_connectivity"][:]),
    )
    areas = np.array(
        [0.0 if polygon is None else float(polygon.area) for polygon in polygons],
        dtype="float64",
    )
    if areas.size < n_cells or not np.any(areas > 0.0):
        return None
    return areas[:n_cells]


def fluxes_from_budget_rows(root: Any, start: int, stop: int) -> np.ndarray:
    """Return ``fluxes_from_budget`` over steps ``[start, stop)``.

    The first stored term of :data:`FLUX_BUDGET_COMPONENTS`, summed over
    layers, divided by the cell area: m3/s over m2, so m/s. Cells of no area
    are NaN. This is the computation the derive step used to store.
    """
    from hydromodpy.results.derive.derived import fluxes_from_budget

    budget = root.get("budget")
    if budget is None:
        raise KeyError("the run kept no per-cell budget")
    component = next((name for name in FLUX_BUDGET_COMPONENTS if name in budget), None)
    if component is None:
        raise KeyError(
            f"No budget component to normalise: expected one of {FLUX_BUDGET_COMPONENTS}"
        )
    n_cells = _cell_count(root)
    area = cell_area_from_mesh(root, n_cells)
    if area is None:
        raise KeyError(
            "Cell area unavailable: the run persisted no mesh geometry to derive it from"
        )

    def compute(first: int, last: int) -> np.ndarray:
        stack = np.asarray(budget[component][first:last], dtype="float64")
        if stack.ndim == 3:
            stack = stack.sum(axis=1)
        stack = stack.reshape(stack.shape[0], -1)[:, :n_cells]
        return np.asarray(fluxes_from_budget(stack, area), dtype="float64")[:, :n_cells]

    return _in_passes(compute, start, stop, n_cells)


SIMULATED_ACTIVE_NETWORK = "simulated_active_network"
"""The cells the network criterion counts as flowing: 1 where a stream flows, else 0."""

SIMULATED_ACTIVE_NETWORK_DESCRIPTOR = FieldDescriptor(
    public_name=SIMULATED_ACTIVE_NETWORK,
    zarr_path=f"derived/{SIMULATED_ACTIVE_NETWORK}",
    standard_name="",
    long_name="Simulated stream network: 1 where the network criterion counts the cell as flowing",
    units="1",
    shape=SHAPE_TIME_FACE,
    cell_methods="time: point area: maximum",
    derived_by="core",
    valid_min=0.0,
    valid_max=1.0,
)
"""The descriptor of the simulated network, a field rebuilt on read and never stored.

It is not in the field registry: the registry lists what a store can hold,
and this field is only ever computed, from the run and its catalog."""


def field_descriptor(name: str) -> FieldDescriptor:
    """Return the descriptor of a field, the rebuilt-only simulated network included."""
    if name == SIMULATED_ACTIVE_NETWORK:
        return SIMULATED_ACTIVE_NETWORK_DESCRIPTOR
    return field_registry.get(name)


def simulated_active_network_stack(run: Any, timesteps: Sequence[int]) -> np.ndarray:
    """Return the simulated stream network of ``run`` at each of ``timesteps``.

    A ``(len(timesteps), n_cells)`` float array of 1 and 0: 1 where the network
    criterion counts the cell as flowing at that step. "Flowing" is the
    definition the criterion scores and the stream maps draw
    (:func:`hydromodpy.core.stream_extent.flowing_cells`), cut with the
    settings of the run's sealed network output: its seepage threshold, its
    graph and its visible flow. A run that sealed none takes the criterion's
    defaults. The graph is built once for every step.

    Raises
    ------
    ValueError
        The run cannot say which cells flow: no ``release_flux``, no network
        to build the graph on, or no recharge for a positive threshold.
    """
    from hydromodpy.core.stream_extent import CHUNK_ELEMENTS, flowing_cells, parse_visible_flow
    from hydromodpy.results.derive.network_criterion_settings import network_criterion_settings
    from hydromodpy.results.derive.stream_extent import (
        FLOW_FIELD,
        flow_geometry_from_run,
        unavailable_reason_for_flow,
    )
    from hydromodpy.results.run.geographic import field_steps

    settings = network_criterion_settings(run)
    reason = unavailable_reason_for_flow(run, tau_specific_ratio=settings.tau_specific_ratio)
    if reason is not None:
        raise ValueError(f"{SIMULATED_ACTIVE_NETWORK} is not available for this run: {reason}.")
    geometry = flow_geometry_from_run(
        run,
        tau_specific_ratio=settings.tau_specific_ratio,
        diagonal_neighbors=settings.diagonal_neighbors,
        observed_rasterization=settings.observed_rasterization,
        observed_position_accuracy_m=settings.observed_position_accuracy_m,
        heads_snap_radius_m=settings.heads_snap_radius_m,
        heads_min_drained_area_km2=settings.heads_min_drained_area_km2,
    )
    visible = parse_visible_flow(settings.extent_rules.visible_flow)
    n_cells = int(geometry.metric.graph.active.size)
    steps = [int(step) for step in timesteps]
    stack = np.zeros((len(steps), n_cells), dtype="float64")
    per_pass = max(1, CHUNK_ELEMENTS // max(1, n_cells))
    for first in range(0, len(steps), per_pass):
        chunk = steps[first : first + per_pass]
        releases = np.asarray(field_steps(run, FLOW_FIELD, chunk), dtype=float)
        for offset, release in enumerate(releases.reshape(len(chunk), -1)):
            state = flowing_cells(
                release,
                threshold_m3_s=geometry.threshold_m3_s,
                metric=geometry.metric,
                visible_flow=visible,
                outlet=geometry.outlet,
            )
            stack[first + offset] = np.asarray(state.flowing, dtype=bool).reshape(-1)
    return stack


def _simulated_active_network(store: Any, sim_id: str, timestep: int) -> np.ndarray:
    """One step of the simulated network, read through the run's catalog."""
    if not callable(getattr(store, "resolve", None)):
        raise KeyError(
            f"{SIMULATED_ACTIVE_NETWORK} is rebuilt from the run and its catalog, "
            "not from a field store alone."
        )
    from hydromodpy.results.run import Run

    return simulated_active_network_stack(Run(str(sim_id), store), [int(timestep)])[0]


def _single_step(rows: Callable[[Any, int, int], np.ndarray]) -> Callable[[Any, str, int], Any]:
    """Return the reader of one step of a field, which is one row of its range path."""

    def read(store: Any, sim_id: str, timestep: int) -> np.ndarray:
        sz = store.open_zarr(sim_id)
        try:
            return _one_step(rows, sz.root, timestep)
        finally:
            sz.close()

    return read


#: Fields rebuilt from per-cell budget terms alone. Their other sources (a stored
#: array, a geometric fallback) are not budget terms, so they are not listed.
BUDGET_ONLY_FIELDS: tuple[str, ...] = (
    "outflow_drain",
    "release_flux",
    "fluxes_from_budget",
    "accumulation_flux",
    "release_accumulation_flux",
)


def budget_terms_kept(root: Any, field: str) -> bool:
    """Say whether the store kept every budget term ``field`` reads.

    Only a store that declares the ``"consumers"`` policy can lack a term. A
    term it declares with no array is a term the model does not produce, which
    is fine. Under ``"all"``, and on a store without attributes, nothing is
    refused here.
    """
    kept = kept_budget(root)
    if kept is None or kept.policy != POLICY_CONSUMERS:
        return True
    return set(budget_terms_for(field)) <= set(kept.terms)


def _needing_kept_terms(field: str, rows: Callable[[Any, int, int], np.ndarray]):
    """Wrap the rows of a budget-only field so a partly kept store refuses it."""

    def gated(root: Any, start: int, stop: int) -> np.ndarray:
        if not budget_terms_kept(root, field):
            raise KeyError(f"The run did not keep every budget term {field} reads")
        return rows(root, start, stop)

    gated.__name__ = rows.__name__
    gated.__doc__ = rows.__doc__
    return gated


# Virtual fields and their whole-range computation, function(root, start,
# stop). A reader wanting many steps takes it: one pass over the stored chunks
# instead of one store opening per step. A single step is one row of it, so a
# step read alone equals the row of a range read.
VIRTUAL_FIELD_ROWS: dict[str, Any] = {
    "watertable_elevation": watertable_elevation_rows,
    "watertable_depth": watertable_depth_rows,
    "seepage_mask": seepage_mask_rows,
    "outflow_drain": outflow_drain_rows,
    "release_flux": release_flux_rows,
    "fluxes_from_budget": fluxes_from_budget_rows,
    "accumulation_flux": accumulation_flux_rows,
    "release_accumulation_flux": release_accumulation_flux_rows,
    "concentration_seepage": concentration_seepage_rows,
    "mass_seepage": mass_seepage_rows,
    "mass_accumulated": mass_accumulated_rows,
}
VIRTUAL_FIELD_ROWS.update(
    {name: _needing_kept_terms(name, VIRTUAL_FIELD_ROWS[name]) for name in BUDGET_ONLY_FIELDS}
)

# Registry: variable name -> computation function(store, sim_id, timestep).
# The simulated network is the exception to the range path: it needs the
# catalog, and an export over several steps builds its graph once through
# simulated_active_network_stack.
VIRTUAL_FIELDS: dict[str, Any] = {
    **{name: _single_step(rows) for name, rows in VIRTUAL_FIELD_ROWS.items()},
    SIMULATED_ACTIVE_NETWORK: _simulated_active_network,
}

# Virtual fields derivable from the persisted head alone (plus mesh topography).
# They are "available" whenever head is stored, so figures find them without a
# persisted derived group.
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
    outflow needs a drain or drain-to-mover term. The release flux needs the
    head (for its cell count) and a budget path out of the aquifer; the unit
    fluxes need the head, a drain or recharge term and the mesh geometry. The
    accumulation fluxes need the head, their budget terms and a descent, stored
    or rebuilt from the mesh topology. The solute chain needs the stored
    concentration: ``concentration_seepage`` also a seepage mask,
    ``mass_seepage`` also a budget group, ``mass_accumulated`` nothing more.
    A field an older run stored under ``derived/`` stands in for its rebuild
    upstream. A store that declares the ``"consumers"`` budget policy serves a
    field built from budget terms only when it kept every term the field reads
    (:func:`budget_terms_kept`), so a partly kept field is refused, not served
    without a word.
    """
    names: list[str] = []
    mesh = root.get("mesh")
    if "head" in root:
        names.append("watertable_elevation")
        if mesh is not None and ("topography" in mesh or "z_interfaces" in mesh):
            names.extend(("watertable_depth", "seepage_mask"))
    budget = root.get("budget")
    if budget is not None and _has_drain_term(budget):
        names.append("outflow_drain")
    if "head" in root and budget is not None:
        if has_release_budget(budget):
            names.append("release_flux")
        has_geometry = mesh is not None and "vertices" in mesh and "face_node_connectivity" in mesh
        if has_geometry and any(name in budget for name in FLUX_BUDGET_COMPONENTS):
            names.append("fluxes_from_budget")
    if accumulation_flux_available(root):
        names.append("accumulation_flux")
    if release_accumulation_flux_available(root):
        names.append("release_accumulation_flux")
    names = [
        name for name in names if name not in BUDGET_ONLY_FIELDS or budget_terms_kept(root, name)
    ]
    names.extend(_solute_fields_available(root, budget))
    return sorted(names)


def _solute_fields_available(root: Any, budget: Any | None) -> list[str]:
    """The solute chain fields this store can serve, each needing the one before it."""
    names: list[str] = []
    rebuildable = "concentration" in root and _seepage_available(root)
    if rebuildable:
        names.append("concentration_seepage")
    if budget is not None and (rebuildable or _has_stored(root, "concentration_seepage")):
        names.append("mass_seepage")
    if _has_stored(root, "mass_seepage") or "mass_seepage" in names:
        names.append("mass_accumulated")
    return names


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
        rows = VIRTUAL_FIELD_ROWS.get(variable)
        if rows is not None and variable in available_virtual_fields(sz.root):
            # Rebuilt on the handle already open, not on a second opening.
            return _one_step(rows, sz.root, timestep)
        result = compute_virtual_field(source, str(sim_id), variable, timestep)
        if result is None:
            raise KeyError(f"Variable '{variable}' not found for sim={sim_id}") from None
        if layer is not None and result.ndim == 2:
            return result[layer]
        return result
    finally:
        sz.close()


def read_field_range_or_virtual(
    source: Any,
    sim_id: str,
    variable: str,
    start: int,
    stop: int,
    layer: int | None = None,
) -> np.ndarray:
    """Read timesteps ``[start, stop)`` of one field with the store opened once.

    Row ``i`` of the stack is what :func:`read_field_or_virtual` returns at
    step ``start + i``, bit for bit. A stored array is sliced directly. A field
    of :data:`VIRTUAL_FIELD_ROWS` is rebuilt over the range in passes. The
    simulated network builds its graph once for the range. Negative bounds
    count from the end. Raises ``KeyError`` when the variable is neither
    persisted nor derivable, ``IndexError`` when the range leaves the time axis.
    """
    sz = source.open_zarr(sim_id)
    try:
        try:
            return sz.read_field_range(variable, start, stop, layer=layer)
        except KeyError:
            return _virtual_range(source, sz, str(sim_id), variable, start, stop)
    finally:
        sz.close()


def _virtual_range(
    source: Any,
    sz: Any,
    sim_id: str,
    variable: str,
    start: int,
    stop: int,
) -> np.ndarray:
    """Rebuild a field that is not stored over ``[start, stop)``, on the open ``sz``."""
    root = sz.root
    first, last = int(start), int(stop)
    n_steps = _time_axis_length(root)
    if n_steps is not None:
        first, last = step_range_bounds(start, stop, n_steps)
    rows = VIRTUAL_FIELD_ROWS.get(variable)
    if rows is not None:
        # A store that cannot serve the field raises the plan's own error, as a step read does.
        return rows(root, first, last)
    if variable == SIMULATED_ACTIVE_NETWORK and callable(getattr(source, "resolve", None)):
        from hydromodpy.results.run import Run

        return simulated_active_network_stack(Run(sim_id, source), range(first, last))
    raise KeyError(f"Variable '{variable}' not found for sim={sim_id}")


class _BorrowedZarr:
    """Non-owning view of an open :class:`SimulationZarr`; ``close`` is a no-op."""

    def __init__(self, handle: Any) -> None:
        self._handle = handle

    @property
    def root(self) -> Any:
        return self._handle.root

    def read_field(self, variable: str, timestep: int, *, layer: int | None = None) -> np.ndarray:
        return self._handle.read_field(variable, timestep, layer=layer)

    def read_field_range(
        self, variable: str, start: int, stop: int, *, layer: int | None = None
    ) -> np.ndarray:
        return self._handle.read_field_range(variable, start, stop, layer=layer)

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
    """Rebuild ``variable`` over ``timesteps`` from an open Zarr handle, or None.

    A field of :data:`VIRTUAL_FIELD_ROWS` is computed once over the range the
    steps span, then the asked rows are picked out of it.
    """
    if variable not in available_virtual_fields(handle.root):
        return None
    steps = np.asarray([int(t) for t in timesteps], dtype=np.int64)
    rows = VIRTUAL_FIELD_ROWS.get(variable)
    if rows is not None and steps.size:
        first = int(steps.min())
        return rows(handle.root, first, int(steps.max()) + 1)[steps - first]
    source = ZarrFieldSource(handle, sim_id)
    return np.stack([np.asarray(source.query_field(sim_id, variable, int(t))) for t in steps])
