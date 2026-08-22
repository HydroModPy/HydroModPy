"""Adapter for the ``flow/modflow6`` solver pair.

This module contains only the MODFLOW 6-specific construction step. The
shared flow execution lifecycle lives in
``hydromodpy.solver.modflow_common.flow_adapter_helpers``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from hydromodpy.core.contracts.observables import ObservableRequest, ObservableResult
from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.base.observables import series_observable
from hydromodpy.solver.modflow6.extractors.lake import extract_lake_series
from hydromodpy.solver.modflow6.modflow6 import Modflow6
from hydromodpy.solver.modflow_common.flow_adapter_helpers import (
    build_preprocess_options,
    resolve_run_model_name,
    run_flow_model,
)
from hydromodpy.solver.modflow_common.observable_extraction import (
    extract_common_modflow_observables,
    resolve_run_output,
)

# LAK observation states this adapter serves, and the unit each carries. The
# request names the state directly now that it also carries the lake in its
# ``key``, so there is no composed ``lake_<quantity>`` variable any more.
_LAKE_STATE_UNITS: dict[str, str] = {
    "stage": "m",
    "volume": "m3",
    "surface_area": "m2",
}


def _collapse_to_disv_cells(
    station_cells: Mapping[str, tuple[int, int, int]],
    model: Any,
) -> dict[str, tuple[int, int, int]]:
    """Map structured ``(layer, row, col)`` station cells to DISV ``(layer, 0, id)``.

    MF6 always writes DISV, whose head array is ``(nlay, 1, ncpl)``. The station
    resolver returns ``(layer, row, col)`` from the structured planar grid, so the
    ``(row, col)`` is collapsed to the flat row-major ``cell2d`` id and the head is
    read as ``head[layer, 0, id]``. Without this, ``head[layer, row, col]`` indexes
    the size-1 middle axis and raises for any station off the first grid row. On an
    unstructured mesh (no ``ncol``) the cells are already flat, so they pass
    through unchanged.
    """
    mesh = getattr(model, "solver_mesh", None)
    if mesh is None or not getattr(mesh, "is_structured", False):
        return dict(station_cells)
    ncol = int(mesh.ncol)
    return {sid: (int(k), 0, int(i) * ncol + int(j)) for sid, (k, i, j) in station_cells.items()}


class Modflow6FlowAdapter:
    """Bridge one planned ``flow/modflow6`` run to the ``Modflow6`` API."""

    process_type = "flow"
    solver_name = "modflow6"
    requires: tuple[tuple[str, str], ...] = ()

    def validate(self, ctx: RunContext) -> None:
        """No precondition checks for MODFLOW 6 flow runs."""

    def cleanup(self, ctx: RunContext) -> None:
        """Remove the scratch directory written by this run, if any."""
        solver_output_dir = ctx.state.execution.output_dirs_by_run_id.get(ctx.run.id)
        if solver_output_dir is not None:
            cleanup_solver_files(solver_output_dir)

    def extract_observables(
        self,
        ctx: RunContext,
        store: Any,
        requests: Sequence[ObservableRequest],
        *,
        time_index: pd.DatetimeIndex | None = None,
    ) -> dict[str, ObservableResult]:
        """Read observables from the scratch CBC, HDS and LAK observation files.

        MF6 binaries share the FloPy-readable format MODFLOW-NWT uses, so
        discharge, head and the per-cell fields come out of the shared helper.
        Lake states are MF6-only: the request names the state in ``name`` and
        the lake in ``key``, and they are read from the LAK observation CSV.
        ``store`` is accepted for Protocol uniformity but unused on this path.
        """
        del store
        if not requests:
            return {}
        output_dir, model, model_name = resolve_run_output(
            ctx, name_attributes=("model_output_name", "model_name", "name")
        )
        served, unserved = extract_common_modflow_observables(
            output_dir,
            model_name,
            model,
            requests,
            time_index=time_index,
            station_cell_mapper=lambda cells: _collapse_to_disv_cells(cells, model),
        )
        for request in unserved:
            if request.support != "lake" or request.name not in _LAKE_STATE_UNITS:
                raise ObservableNotAvailableError(
                    f"MODFLOW 6 does not produce observable {request.name!r} on support "
                    f"{request.support!r}."
                )
            series = extract_lake_series(
                output_dir,
                model_name,
                lake_id=str(request.key),
                quantity=request.name,
                time_index=time_index,
            )
            served[request.id] = series_observable(
                request, series, units=_LAKE_STATE_UNITS[request.name]
            )
        return served

    @staticmethod
    def _solver_runtime_cache(state) -> dict[tuple[str, str, str], Modflow6]:
        cache = getattr(state.setup, "_flow_solver_runtime_cache", None)
        if isinstance(cache, dict):
            return cache
        cache = {}
        state.setup._flow_solver_runtime_cache = cache
        return cache

    @staticmethod
    def _reuse_solver_model_enabled(state) -> bool:
        overrides = getattr(state.setup, "flow_runtime_overrides", None)
        return bool(isinstance(overrides, Mapping) and overrides.get("reuse_solver_model", False))

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one MODFLOW 6 flow run.

        The method is intentionally narrow in scope:

        - resolve the shared preprocessing options,
        - derive the stable model folder name for this run,
        - build the concrete ``Modflow6`` object,
        - delegate the common run lifecycle to ``run_flow_model``.
        """

        state = ctx.state
        if self._reuse_solver_model_enabled(state):
            raise NotImplementedError(
                "flow_runtime_overrides['reuse_solver_model'] is disabled: solver-model reuse "
                "was validated as NOT output-equivalent (identical parameters produced different "
                "objectives). Profiling (2026-07) also found the per-trial model build is small "
                "(a lightweight trial builds in ~0.1 s; the solve dominates), so reuse trades a "
                "real correctness risk for a negligible speedup. Re-enable it only behind an "
                "integration test that asserts objective equality versus a full rebuild."
            )
        preprocess_options = build_preprocess_options(state)
        model_name = resolve_run_model_name(ctx)
        model_modflow = None
        if self._reuse_solver_model_enabled(state):
            cache = self._solver_runtime_cache(state)
            cache_key = (self.solver_name, str(ctx.run.id), str(model_name))
            model_modflow = cache.get(cache_key)
            if model_modflow is None:
                model_modflow = Modflow6(
                    state.setup.geographic,
                    model_folder=state.setup.workspace.simulations_folder,
                    model_name=model_name,
                    bin_path=state.setup.workspace.bin_path,
                    modflow_config=state.cfg.modflow6,
                    preprocess_options=preprocess_options,
                )
                cache[cache_key] = model_modflow
        # This is the only MODFLOW 6-specific part of the adapter: wiring the
        # MF6 config block into the concrete solver implementation.
        if model_modflow is None:
            model_modflow = Modflow6(
                state.setup.geographic,
                model_folder=state.setup.workspace.solver_scratch_folder,
                model_name=model_name,
                bin_path=state.setup.workspace.bin_path,
                modflow_config=state.cfg.modflow6,
                preprocess_options=preprocess_options,
            )
        return run_flow_model(ctx, model_modflow, preprocess_options)
