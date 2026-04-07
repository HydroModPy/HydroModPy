"""Adapter for the ``flow/boussinesq`` solver pair.

This adapter is intentionally independent from ``modflow_common``. The
``boussinesq`` backend can now consume either:

- one gmsh-derived ``CatchmentMeshBundle`` (historical fallback), or
- one runtime Gmsh planar mesh together with ``Flow``/``Domain`` property
  mapping in the same spirit as the MODFLOW adapters.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.spatial.geographic.core.derived_features import resolve_river_mesh_trace
from hydromodpy.solver.boussinesq import Boussinesq
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.property_mapping import (
    resolve_flow_property_arrays,
    resolve_required_flow_properties,
)
from hydromodpy.solver.utils.mesh.gmsh_grid import load_planar_mesh
from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
    load_catchment_mesh_bundle,
)


def _resolve_planar_mesh(setup_state: object):
    """Return the canonical runtime Gmsh planar mesh attached to launcher setup."""
    preloaded = getattr(setup_state, "mesh_planar", None)
    if preloaded is not None:
        return preloaded

    mesh_summary = getattr(setup_state, "mesh_summary", None)
    if isinstance(mesh_summary, dict):
        mesh_path = str(mesh_summary.get("output_mesh", "")).strip()
        if mesh_path != "":
            mesh = load_planar_mesh(Path(mesh_path).expanduser())
            setattr(setup_state, "mesh_planar", mesh)
            return mesh
    return None


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
        "flow/boussinesq requires either a runtime planar mesh with Flow/Domain "
        "property mapping support, or one CatchmentMeshBundle from the gmsh mesh "
        "workflow. Provide state.setup.mesh_planar or state.setup.mesh_bundle, "
        "or run the embedded [mesh_catchment] phase so output_mesh or "
        "output_exchange_bundle_dir is available."
    )


def _has_required_flow_parameters(*, flow: object, required_properties: frozenset[str]) -> bool:
    """Tell whether the Flow runtime already exposes the direct-mapping properties."""
    parameters = getattr(flow, "parameters", {})
    if not isinstance(parameters, dict):
        return False

    alias_map = {
        "K": ("K", "k"),
        "Sy": ("Sy", "SY", "sy", "S", "s"),
    }
    for canonical_name in required_properties:
        aliases = alias_map.get(canonical_name, ())
        if not any(alias in parameters for alias in aliases):
            return False
    return True


def _flow_uses_stream_bc(flow: object) -> bool:
    """Tell whether the current Flow run activates the stream boundary condition."""
    active_bc = getattr(flow, "active_bc", ())
    return any(str(bc_id).strip().lower() == "stream" for bc_id in active_bc or ())


def _resolve_runtime_solver_mesh(setup_state: object) -> BoussinesqMesh | None:
    """Build one direct solver mesh from runtime mesh + Flow/Domain mapping."""
    planar_mesh = _resolve_planar_mesh(setup_state)
    if planar_mesh is None:
        return None

    flow = getattr(setup_state, "flow", None)
    domain = getattr(setup_state, "domain", None)
    if flow is None or domain is None:
        return None

    required_properties = resolve_required_flow_properties(
        flow_regime=str(getattr(flow, "flow_regime", "transient"))
    )
    if not _has_required_flow_parameters(
        flow=flow,
        required_properties=required_properties,
    ):
        return None

    property_arrays = resolve_flow_property_arrays(
        flow=flow,
        domain=domain,
        solver_mesh=planar_mesh,
        required_properties=required_properties,
    )
    conductivity = np.asarray(
        property_arrays["hydraulic_conductivity_m_s"],
        dtype=float,
    )
    storage = np.asarray(
        property_arrays.get(
            "storage_coefficient",
            np.zeros(int(planar_mesh.n_cells), dtype=float),
        ),
        dtype=float,
    )
    geographic_features = getattr(setup_state, "geographic_features", None)
    domain_geographic = getattr(setup_state, "domain_geographic", None)
    river_trace = resolve_river_mesh_trace(
        geographic_features=geographic_features,
        domain_geographic=domain_geographic,
    )
    if _flow_uses_stream_bc(flow) and river_trace is None:
        return None
    return BoussinesqMesh.from_planar_mesh(
        planar_mesh,
        domain=domain,
        hydraulic_conductivity_m_s=conductivity,
        storage_coefficient=storage,
        river_trace=river_trace,
    )


class BoussinesqFlowAdapter:
    """Bridge one planned ``flow/boussinesq`` run to the local solver API."""

    process_type = "flow"
    solver_name = "boussinesq"

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one Boussinesq flow run."""
        state = ctx.state
        solver_mesh = _resolve_runtime_solver_mesh(state.setup)
        mesh_bundle = None if solver_mesh is not None else _resolve_mesh_bundle(state.setup)
        workspace = getattr(state.setup, "workspace", None)
        model_folder = (
            Path(getattr(workspace, "simulations_folder"))
            if workspace is not None
            else Path.cwd()
        )
        model_name = ctx.run.id.replace("::", "__")

        model = Boussinesq(
            mesh_bundle=mesh_bundle,
            mesh=solver_mesh,
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
