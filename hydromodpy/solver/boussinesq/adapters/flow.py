"""Adapter for the ``flow/boussinesq`` solver pair.

This module contains only the Boussinesq-specific construction step. The
mesh-resolution helpers live in
``hydromodpy.solver.boussinesq.flow_to_boussinesq_adapter`` so the adapter
file stays symmetrical with the MODFLOW adapters.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

from hydromodpy.core.contracts.observables import (
    ObservableRequest,
    ObservableResult,
    require_unique_request_ids,
)
from hydromodpy.core.exceptions import (
    ObservableNotAvailableError,
    SolverDivergedError,
    SolverError,
)
from hydromodpy.core.state.paths import share_dir_for
from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.base.observables import series_observable
from hydromodpy.solver.boussinesq.boussinesq import Boussinesq
from hydromodpy.solver.boussinesq.calibration_extractors import (
    extract_discharge_history,
    extract_head_history_at_cells,
)
from hydromodpy.solver.boussinesq.flow_to_boussinesq_adapter import (
    resolve_bundle_solver_mesh,
    resolve_mesh_bundle,
    resolve_runtime_solver_mesh,
)
from hydromodpy.solver.boussinesq.runtimes.ts_vi_obstacle_diagnostics import (
    write_ts_vi_obstacle_diagnostic_files,
)
from hydromodpy.solver.boussinesq.runtimes.vi_obstacle_diagnostics import (
    write_vi_obstacle_diagnostic_files,
)


class BoussinesqFlowAdapter:
    """Bridge one planned ``flow/boussinesq`` run to the local solver API."""

    process_type = "flow"
    solver_name = "boussinesq"
    requires: tuple[tuple[str, str], ...] = ()

    def validate(self, ctx: RunContext) -> None:
        """No precondition checks for Boussinesq flow runs."""

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
        """Read observables from the Boussinesq scratch directory.

        Discharge is reconstructed from ``drainage_flux_history_m3_s`` summed
        over all cells per timestep, which is the MODFLOW DRAIN convention.
        Heads are read at flattened cell indices: the Boussinesq mesh is one
        unstructured layer, so a ``(k, i, j)`` cell is read as ``cell_id = j``.
        Every head request is served in one pass over the history.
        """
        del store
        if not requests:
            return {}
        require_unique_request_ids(requests)
        output_dir = ctx.state.execution.output_dirs_by_run_id.get(ctx.run.id)
        if output_dir is None:
            raise SolverError(f"No solver output recorded for run {ctx.run.id!r}")
        output_dir = Path(output_dir)

        served: dict[str, ObservableResult] = {}
        head_requests = [r for r in requests if r.name == "head" and r.support == "cell"]
        discharge_requests = [
            r for r in requests if r.name == "discharge" and r.support == "domain"
        ]
        handled = {id(r) for r in head_requests + discharge_requests}
        for request in requests:
            if id(request) not in handled:
                raise ObservableNotAvailableError(
                    f"Boussinesq does not produce observable {request.name!r} on support "
                    f"{request.support!r}."
                )

        if discharge_requests:
            series = extract_discharge_history(output_dir, time_index=time_index)
            for request in discharge_requests:
                served[request.id] = series_observable(request, series, units="m3 s-1")

        if head_requests:
            station_cells = {r.id: r.cell for r in head_requests}
            series_by_station = extract_head_history_at_cells(
                output_dir,
                station_cells=station_cells,
                time_index=time_index,
            )
            for request in head_requests:
                try:
                    series = series_by_station[request.id]
                except KeyError as exc:
                    raise KeyError(f"No head series extracted for station {request.id!r}") from exc
                served[request.id] = series_observable(request, series, units="m")

        return served

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one Boussinesq flow run."""
        state = ctx.state
        mesh_bundle = None
        try:
            solver_mesh = resolve_runtime_solver_mesh(state.setup)
        except ValueError:
            mesh_summary = getattr(state.setup, "mesh_summary", None)
            bundle_dir = (
                str(mesh_summary.get("output_exchange_bundle_dir", "")).strip()
                if isinstance(mesh_summary, dict)
                else ""
            )
            if getattr(state.setup, "mesh_bundle", None) is None and bundle_dir == "":
                raise
            solver_mesh = None
        if solver_mesh is None:
            mesh_bundle = resolve_mesh_bundle(state.setup)
            solver_mesh = resolve_bundle_solver_mesh(state.setup, bundle=mesh_bundle)
        runtime_mesh_support = getattr(state.setup, "mesh_support", None)
        if runtime_mesh_support is not None:
            solver_mesh = replace(solver_mesh, support_metadata=runtime_mesh_support)
        workspace = getattr(state.setup, "workspace", None)
        model_folder = (
            Path(workspace.solver_scratch_folder) if workspace is not None else Path.cwd()
        )

        model = Boussinesq(
            mesh_bundle=mesh_bundle,
            mesh=solver_mesh,
            flow=state.setup.flow,
            domain=state.setup.domain,
            time_grid=getattr(state.setup, "time_grid", None),
            model_folder=model_folder,
            model_name=ctx.run.id.replace("::", "__"),
        )
        model.pre_processing()
        success = model.processing(write_model=True, run_model=True)
        if not success:
            raise SolverDivergedError(
                f"[HMPY.E401] Flow solver 'boussinesq' failed for run '{ctx.run.id}'. "
                f"See {getattr(model, 'full_path', '<unknown>')} for diagnostics.",
                run_id=ctx.run.id,
            )
        self._persist_obstacle_diagnostics(ctx, model)

        metrics: dict[str, float] = {}
        flow_solve_time = getattr(model, "last_flow_solve_time_seconds", None)
        if flow_solve_time is not None:
            metrics["flow_solve_time_seconds"] = float(flow_solve_time)
        return RunExecutionResult(
            primary_model=model,
            solver_output_dir=Path(model.full_path) if hasattr(model, "full_path") else None,
            metrics=metrics,
        )

    @staticmethod
    def _persist_obstacle_diagnostics(ctx: RunContext, model: Boussinesq) -> None:
        """Copy VI runtime diagnostics to a stable workspace path before cleanup."""
        workspace = getattr(ctx.state.setup, "workspace", None)
        if workspace is None or not hasattr(model, "full_path"):
            return
        project_root = getattr(workspace, "project_root", None) or getattr(workspace, "root", None)
        if project_root is None:
            return
        summary_path = Path(model.full_path) / "_boussinesq_summary.json"
        if not summary_path.exists():
            return
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        run_id = str(getattr(ctx.state.setup, "run_id", "") or ctx.run.id)
        diagnostics_dir = share_dir_for(Path(project_root)) / run_id / "solver_diagnostics"
        write_vi_obstacle_diagnostic_files(diagnostics_dir, summary)
        write_ts_vi_obstacle_diagnostic_files(diagnostics_dir, summary)


__all__ = ["BoussinesqFlowAdapter"]
