"""Adapter for the ``flow/boussinesq`` solver pair.

This adapter is intentionally independent from ``modflow_common``. The
``boussinesq`` backend consumes one gmsh-derived ``CatchmentMeshBundle`` and
builds its own in-memory mesh/runtime state without any MODFLOW package layer.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.boussinesq import Boussinesq
from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
    load_catchment_mesh_bundle,
)


def _resolve_mesh_bundle(setup_state: object) -> CatchmentMeshBundle:
    """Return the canonical gmsh catchment bundle attached to launcher setup."""
    preloaded = getattr(setup_state, "mesh_bundle", None)
    if preloaded is not None:
        return preloaded

    mesh_summary = getattr(setup_state, "mesh_summary", None)
    if isinstance(mesh_summary, dict):
        bundle_dir = str(mesh_summary.get("output_exchange_bundle_dir", "")).strip()
        if bundle_dir != "":
            bundle = load_catchment_mesh_bundle(bundle_dir)
            setattr(setup_state, "mesh_bundle", bundle)
            return bundle

    raise ValueError(
        "flow/boussinesq requires one CatchmentMeshBundle from the gmsh mesh "
        "workflow. Provide state.setup.mesh_bundle or run the embedded "
        "[mesh_catchment] phase so output_exchange_bundle_dir is available."
    )


class BoussinesqFlowAdapter:
    """Bridge one planned ``flow/boussinesq`` run to the local solver API."""

    process_type = "flow"
    solver_name = "boussinesq"

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one Boussinesq flow run."""
        state = ctx.state
        mesh_bundle = _resolve_mesh_bundle(state.setup)
        workspace = getattr(state.setup, "workspace", None)
        model_folder = (
            Path(getattr(workspace, "simulations_folder"))
            if workspace is not None
            else Path.cwd()
        )
        model_name = ctx.run.id.replace("::", "__")

        model = Boussinesq(
            mesh_bundle=mesh_bundle,
            flow=state.setup.flow,
            domain=state.setup.domain,
            time_grid=getattr(state.setup, "time_grid", None),
            model_folder=model_folder,
            model_name=model_name,
        )
        model.pre_processing()
        success = model.processing(write_model=True, run_model=True)
        if not success:
            raise RuntimeError(
                f"Flow solver 'boussinesq' failed for run '{ctx.run.id}'. "
                f"See {getattr(model, 'full_path', '<unknown>')} for diagnostics."
            )
        model.post_processing()
        return RunExecutionResult(primary_model=model)


__all__ = ["BoussinesqFlowAdapter"]
