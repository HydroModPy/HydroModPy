"""The per-cell budget of a MODFLOW 6 run, read from its CBC file into the store.

One budget slice per saved head, and the build saves the head at the end of
each stress period. A stamp closes its period, so each flux is the mean of the
time steps since the previous stamp, weighted by their length.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.budget.flux import STREAM_CONSTANT_HEAD_BUDGET
from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.console import progress
from hydromodpy.core.logging import get_logger
from hydromodpy.core.scope import CATCHMENT, DOMAIN
from hydromodpy.solver.modflow_common.budget_components import (
    canonical_budget_component,
    is_scalar_budget_component,
)
from hydromodpy.solver.modflow_common.budget_policy import record_budget_policy
from hydromodpy.solver.modflow_common.field_slab import slab_steps
from hydromodpy.solver.modflow_common.period_steps import (
    group_steps_by_stamp,
    weighted_period_mean,
    weighted_period_scalar,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class _PeriodBudget:
    """One budget record averaged over the steps of one stamp, in m3/s.

    ``field`` stays in the TDIS unit, as the cell budget file holds it.
    """

    flux_in: float
    flux_out: float
    basin_in: float | None
    basin_out: float | None
    field: np.ndarray | None


def _records_by_stamp(
    records: Sequence[Any],
    component_rank: dict[str, int],
    *,
    stamp_keys: Sequence[tuple[int, int]],
) -> list[dict[str, list[tuple[int, float]]]]:
    """Index the budget records under the stamp that closes their step.

    Returns, per stamp, the records of each scalar component as
    ``(record index, step weight)``. ``stamp_keys`` are the 1-based
    ``(kstp, kper)`` of the saved heads. The step weight is the step length
    over the length of the steps the stamp closes.
    """
    step_position: dict[tuple[int, int], int] = {}
    step_lengths: list[float] = []
    for record in records:
        key = (int(record.kstp), int(record.kper))
        if key not in step_position:
            step_position[key] = len(step_lengths)
            step_lengths.append(float(record.delt))
    groups = group_steps_by_stamp(list(step_position), step_lengths, stamp_keys)
    placed: dict[int, tuple[int, float]] = {}
    for group in groups:
        for position, weight in zip(group.positions, group.weights, strict=True):
            placed[position] = (group.stamp, weight)
    by_stamp: list[dict[str, list[tuple[int, float]]]] = [{} for _ in stamp_keys]
    seen: set[tuple[str, int]] = set()
    warned_duplicate: set[str] = set()
    for idx, record in enumerate(records):
        component = record.text
        if component not in component_rank:
            continue
        position = step_position[(int(record.kstp), int(record.kper))]
        stamp_weight = placed.get(position)
        if stamp_weight is None:
            continue
        if (component, position) in seen:
            # Several packages of one type share the record name; keep
            # the first record like the historical data[0] read did.
            if component not in warned_duplicate:
                logger.warning(
                    "MF6 budget has multiple '%s' package records per timestep; "
                    "keeping the first (aggregate views may undercount).",
                    component,
                )
                warned_duplicate.add(component)
            continue
        seen.add((component, position))
        stamp, weight = stamp_weight
        by_stamp[stamp].setdefault(component, []).append((idx, weight))
    return by_stamp


def extract_budget(
    sim_id: str,
    store: Any,
    cbc_path: Path,
    times: list,
    kstpkpers: list,
    *,
    budget_terms: BudgetKeep = BudgetKeep.everything(),
    nlay: int = 1,
    n_cells: int = 0,
    seconds_per_time_unit: float = 1.0,
    catchment_mask: np.ndarray | None = None,
    stream_constant_head_mask: np.ndarray | None = None,
) -> None:
    """Extract cell budget data from MF6 .cbc file.

    One budget slice per saved head, and the build saves the head at the
    end of each stress period. A stamp closes its period, so each flux
    is the mean of the time steps since the previous stamp, weighted by
    their length (the ``delt`` of each record). A stamp that closes one
    step keeps that step unchanged.

    Fluxes are divided by ``seconds_per_time_unit`` so the stored values are
    m3/s regardless of the TDIS time unit (m3/s = flux / seconds_per_time_unit).

    With ``stream_constant_head_mask``, the per-cell constant-head flux is
    also written restricted to the stream-role cells, as
    ``budget/constant_head_stream``. That spatial field is the stream-role
    CHD term of ``release_flux``; it gets no budget table row, since the
    ``constant_head`` row already counts that water.

    The budget table holds every scalar record. A per-cell field is built
    only for a term ``budget_terms`` reads and written only for a term it
    keeps; ``constant_head_stream`` is written whenever it is kept, even
    when ``constant_head`` is not. The ``budget/`` attributes record the
    policy and the terms kept.
    """
    from hydromodpy.solver.modflow6.extractors.cbc_reader import Mf6CellBudgetReader

    cbb = Mf6CellBudgetReader(cbc_path)
    catchment_cells = np.flatnonzero(catchment_mask) if catchment_mask is not None else None
    if catchment_cells is not None and catchment_cells.size == 0:
        # A row of zeros under a name that claims to be the catchment reads
        # as a dry basin instead of as a missing mask.
        catchment_cells = None
    spt = seconds_per_time_unit
    try:
        # Intercell face flows and the specific-discharge velocity are not
        # scalar budget terms; skip them before reading or summing.
        components = [
            name for name in cbb.unique_record_names() if is_scalar_budget_component(name)
        ]
        component_rank = {name: rank for rank, name in enumerate(components)}
        built = {
            name
            for name in components
            if budget_terms.reads_record(canonical_budget_component(name))
        }
        keep_stream_chd = stream_constant_head_mask is not None and budget_terms.keeps(
            STREAM_CONSTANT_HEAD_BUDGET
        )

        n_timesteps = len(times)
        # One sequential pass over the file-order record index. Per-record
        # get_data(text, kstpkper, totim) calls rebuild a full boolean mask of
        # the index each time, which is quadratic over a long chronicle.
        records_by_stamp = _records_by_stamp(
            cbb.records,
            component_rank,
            stamp_keys=[(int(kstp) + 1, int(kper) + 1) for kstp, kper in kstpkpers],
        )
        # The cbc file is time-major, so budget spatial fields are streamed in
        # time slabs shared across the components built: the slab is sized so
        # they together stay under one field-slab budget rather than holding
        # every component's full (nper, nlay, ncpl) stack in RAM.
        budget_slab = max(1, slab_steps(nlay, n_cells) // max(1, len(built)))
        created_fields: set[str] = set()
        ranked_records: list[tuple[int, int, dict]] = []
        slab_stacks: dict[str, np.ndarray] = {}
        window_t0 = 0

        def _write_budget_stack(comp_key: str, stack: np.ndarray, t0: int) -> None:
            try:
                if comp_key not in created_fields and t0 != 0:
                    # First write of a variable must start at offset 0;
                    # prime the full array for a component that only
                    # appears past the first slab (rare for per-step terms).
                    primer = np.full((1, *stack.shape[1:]), np.nan, dtype="float64")
                    store.write_field_stack(
                        sim_id,
                        comp_key,
                        primer,
                        n_timesteps=n_timesteps,
                        timestep_offset=0,
                        subgroup="budget",
                    )
                store.write_field_stack(
                    sim_id,
                    comp_key,
                    stack,
                    n_timesteps=n_timesteps,
                    timestep_offset=t0,
                    subgroup="budget",
                )
                created_fields.add(comp_key)
            except Exception:
                logger.debug(
                    "Skipped write_field_stack for MF6 budget '%s'", comp_key, exc_info=True
                )

        def _flush_window(t0: int) -> None:
            for comp, stack in slab_stacks.items():
                comp_key = canonical_budget_component(comp)
                if budget_terms.keeps(comp_key):
                    _write_budget_stack(comp_key, stack, t0)
                if comp_key == "constant_head" and keep_stream_chd:
                    _write_budget_stack(
                        STREAM_CONSTANT_HEAD_BUDGET,
                        np.where(stream_constant_head_mask, stack, 0.0),
                        t0,
                    )
            slab_stacks.clear()

        n_reads = sum(len(steps) for by in records_by_stamp for steps in by.values())
        with progress.task("Extracting budget terms", total=n_reads) as handle:
            for t, by_component in enumerate(records_by_stamp):
                if built and t >= window_t0 + budget_slab:
                    _flush_window(window_t0)
                    window_t0 = (t // budget_slab) * budget_slab
                for component, steps in by_component.items():
                    handle.advance(len(steps))
                    mean = _period_mean_record(
                        cbb,
                        steps,
                        component=component,
                        t=t,
                        nlay=nlay,
                        n_cells=n_cells,
                        seconds_per_time_unit=spt,
                        catchment_cells=catchment_cells,
                        with_field=component in built,
                    )
                    if mean is None:
                        continue
                    rank = component_rank[component]
                    canonical = canonical_budget_component(component)
                    ranked_records.append(
                        (
                            t,
                            rank,
                            {
                                "timestep": t,
                                "zone_id": DOMAIN,
                                "component": canonical,
                                "flux_in": mean.flux_in,
                                "flux_out": abs(mean.flux_out),
                                "unit": "m3 s-1",
                            },
                        )
                    )
                    if mean.basin_in is not None:
                        # The row above spans the model domain. On a buffered
                        # box that is not what a gauge at the outlet sees, and
                        # the per-cell field is dropped right after unless
                        # the run keeps the term. Summing the basin here, where
                        # the array is already in memory, is what lets a run
                        # carry a catchment-supported budget for free.
                        ranked_records.append(
                            (
                                t,
                                rank,
                                {
                                    "timestep": t,
                                    "zone_id": CATCHMENT,
                                    "component": canonical,
                                    "flux_in": mean.basin_in,
                                    "flux_out": abs(mean.basin_out),
                                    "unit": "m3 s-1",
                                },
                            )
                        )
                    if mean.field is not None:
                        field = mean.field
                        stack = slab_stacks.get(component)
                        if stack is None:
                            slab_len = min(budget_slab, n_timesteps - window_t0)
                            stack = np.full((slab_len, *field.shape), np.nan, dtype="float64")
                            slab_stacks[component] = stack
                        if stack.shape[1:] == field.shape:
                            stack[t - window_t0] = field / spt

        _flush_window(window_t0)

        # Keep the historical order: time-major, then component declaration order.
        ranked_records.sort(key=lambda item: (item[0], item[1]))
        budget_records = [record for _, _, record in ranked_records]
        if budget_records:
            store.write_budgets(sim_id, budget_records)
    finally:
        cbb.close()
    record_budget_policy(store, sim_id, budget_terms, created_fields)


def _period_mean_record(
    cbb: Any,
    steps: list[tuple[int, float]],
    *,
    component: str,
    t: int,
    nlay: int,
    n_cells: int,
    seconds_per_time_unit: float,
    catchment_cells: np.ndarray | None,
    with_field: bool = True,
) -> _PeriodBudget | None:
    """Weighted mean over the steps of one stamp of one budget record.

    The in and out totals are the means of the step totals, so a cell that
    changes sign within the period counts its inflow and its outflow, as
    the volumes of the period do. The cell field is the mean of the step
    fields, in the TDIS unit, computed only ``with_field``. None when no
    step could be read.
    """
    spt = seconds_per_time_unit
    weights: list[float] = []
    flux_in: list[float] = []
    flux_out: list[float] = []
    basin_in: list[float] = []
    basin_out: list[float] = []
    fields: list[np.ndarray] = []
    field_weights: list[float] = []
    for idx, weight in steps:
        try:
            arr = cbb.read_record(idx)
        except Exception as exc:
            logger.debug("Could not read MF6 budget '%s' at t=%d: %s", component, t, exc)
            continue
        if hasattr(arr, "dtype") and arr.dtype.names is not None:
            arr = _recarray_to_grid(arr, nlay, n_cells)
        field = None
        if hasattr(arr, "shape") and arr.ndim >= 1:
            flux_in.append(float(np.maximum(arr, 0).sum()) / spt)
            flux_out.append(float(np.minimum(arr, 0).sum()) / spt)
            field = _as_cell_grid(arr, nlay, n_cells)
        else:
            flux_in.append(0.0)
            flux_out.append(0.0)
        weights.append(weight)
        if field is not None:
            fields.append(field)
            field_weights.append(weight)
            if catchment_cells is not None:
                in_basin = field[:, catchment_cells]
                basin_in.append(float(np.maximum(in_basin, 0).sum()) / spt)
                basin_out.append(float(np.minimum(in_basin, 0).sum()) / spt)
    if not weights:
        return None
    has_basin = catchment_cells is not None and bool(fields)
    return _PeriodBudget(
        flux_in=weighted_period_scalar(flux_in, weights),
        flux_out=weighted_period_scalar(flux_out, weights),
        basin_in=weighted_period_scalar(basin_in, field_weights) if has_basin else None,
        basin_out=weighted_period_scalar(basin_out, field_weights) if has_basin else None,
        field=weighted_period_mean(fields, field_weights) if fields and with_field else None,
    )


def _recarray_to_grid(
    rec: np.ndarray,
    nlay: int,
    n_cells: int,
) -> np.ndarray:
    """Convert a MF6 stress-package recarray to a full grid array.

    MF6 stress packages store sparse records with 1-based ``node``
    IDs and ``q`` flux values.  This scatters them into a dense
    ``(nlay, n_cells)`` array. Vector records (DATA-SPDIS) are excluded
    upstream by ``is_scalar_budget_component`` and never reach here.
    """
    names = rec.dtype.names
    q = np.asarray(
        rec["q"] if names is not None and "q" in names else rec[names[-1]], dtype="float64"
    )

    if n_cells == 0:
        return q

    nodes = np.asarray(rec["node"], dtype="int64") if "node" in names else None
    out = np.zeros((nlay, n_cells), dtype="float64")
    if nodes is not None:
        idx = nodes - 1
        lay = idx // n_cells
        cell = idx % n_cells
        valid = (lay >= 0) & (lay < nlay) & (cell >= 0) & (cell < n_cells)
        np.add.at(out, (lay[valid], cell[valid]), q[valid])
    else:
        n = min(len(q), n_cells)
        out[0, :n] = q[:n]
    return out


def _as_cell_grid(arr: Any, nlay: int, n_cells: int) -> np.ndarray | None:
    """Reshape one budget record to ``(nlay, n_cells)``, None when it does not fit."""
    if arr.size == nlay * n_cells:
        return np.asarray(arr).reshape(nlay, n_cells)
    if arr.ndim == 1 and arr.size == n_cells:
        return np.asarray(arr).reshape(1, n_cells)
    return None


__all__ = ["extract_budget"]
