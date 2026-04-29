"""Adapter for the ``flow/boussinesq`` solver pair.

This module contains only the Boussinesq-specific construction step. The
mesh-resolution helpers live in
``hydromodpy.solver.boussinesq.flow_to_boussinesq_adapter`` so the adapter
file stays symmetrical with the MODFLOW adapters.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.boussinesq.boussinesq import Boussinesq
from hydromodpy.solver.boussinesq.flow_to_boussinesq_adapter import (
    resolve_bundle_solver_mesh,
    resolve_mesh_bundle,
    resolve_runtime_solver_mesh,
)


class BoussinesqFlowAdapter:
    """Bridge one planned ``flow/boussinesq`` run to the local solver API."""

    process_type = "flow"
    solver_name = "boussinesq"
    requires: tuple[tuple[str, str], ...] = ()

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
            raise RuntimeError(
                f"Flow solver 'boussinesq' failed for run '{ctx.run.id}'. "
                f"See {getattr(model, 'full_path', '<unknown>')} for diagnostics."
            )

        return RunExecutionResult(
            primary_model=model,
            solver_output_dir=Path(model.full_path) if hasattr(model, "full_path") else None,
        )


__all__ = ["BoussinesqFlowAdapter"]
