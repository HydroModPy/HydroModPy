"""Adapter for the ``flow/boussinesq`` solver pair.

This adapter is intentionally independent from the MODFLOW helpers. The
``boussinesq`` backend can consume either:

- one gmsh-derived ``CatchmentMeshBundle`` (historical fallback), or
- one runtime Gmsh planar mesh together with ``Flow``/``Domain`` property
  mapping in the same spirit as the MODFLOW adapters.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.boussinesq.boussinesq import Boussinesq
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
from hydromodpy.spatial.geographic.core.derived_features import resolve_river_mesh_trace


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
            setup_state.mesh_planar = mesh
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
            setup_state.mesh_bundle = bundle
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


def _has_any_flow_parameter(*, flow: object, canonical_name: str) -> bool:
    """Tell whether one canonical flow parameter alias is available."""
    alias_map = {
        "K": ("K", "k"),
        "Sy": ("Sy", "SY", "sy", "S", "s"),
    }
    parameters = getattr(flow, "parameters", {})
    if not isinstance(parameters, dict):
        return False
    aliases = alias_map.get(str(canonical_name).strip(), ())
    return any(alias in parameters for alias in aliases)


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


def _resolve_optional_bundle_property_arrays(
    *,
    setup_state: object,
    requested_properties: frozenset[str],
) -> dict[str, np.ndarray]:
    """Map available flow properties onto the bundle planar mesh when requested."""
    if not requested_properties:
        return {}

    planar_mesh = _resolve_planar_mesh(setup_state)
    flow = getattr(setup_state, "flow", None)
    if planar_mesh is None or flow is None:
        return {}

    available_properties = frozenset(
        canonical_name
        for canonical_name in requested_properties
        if _has_any_flow_parameter(flow=flow, canonical_name=canonical_name)
    )
    if not available_properties:
        return {}

    return resolve_flow_property_arrays(
        flow=flow,
        domain=getattr(setup_state, "domain", None),
        solver_mesh=planar_mesh,
        required_properties=available_properties,
    )


def _resolve_bundle_solver_mesh(
    setup_state: object,
    *,
    bundle: CatchmentMeshBundle,
) -> BoussinesqMesh:
    """Build one solver mesh from a bundle, completing missing hydraulic terms."""
    flow = getattr(setup_state, "flow", None)
    regime = str(getattr(flow, "flow_regime", "transient")).strip().lower()
    metadata_view = bundle.metadata_view
    hydraulic_view = metadata_view.hydraulic_properties

    needs_conductivity = any(cell.hydraulic_conductivity_m_s is None for cell in bundle.cells)
    needs_storage = any(cell.storage_coefficient is None for cell in bundle.cells)
    needed_properties: set[str] = set()
    if needs_conductivity and hydraulic_view.conductivity.default_value is None:
        needed_properties.add("K")
    if needs_storage:
        if hydraulic_view.storage_coefficient.default_value is None:
            has_flow_sy = flow is not None and _has_any_flow_parameter(
                flow=flow, canonical_name="Sy"
            )
            if regime != "steady" or has_flow_sy:
                needed_properties.add("Sy")

    override_properties: set[str] = set()
    if flow is not None:
        if _has_any_flow_parameter(flow=flow, canonical_name="K"):
            override_properties.add("K")
        if _has_any_flow_parameter(flow=flow, canonical_name="Sy"):
            override_properties.add("Sy")

    property_arrays = _resolve_optional_bundle_property_arrays(
        setup_state=setup_state,
        requested_properties=frozenset(needed_properties | override_properties),
    )
    mapped_conductivity = property_arrays.get("hydraulic_conductivity_m_s")
    mapped_storage = property_arrays.get("storage_coefficient")

    completed_cells = []
    for cell_index, bundle_cell in enumerate(bundle.cells):
        conductivity = (
            float(mapped_conductivity[cell_index])
            if mapped_conductivity is not None
            else bundle_cell.hydraulic_conductivity_m_s
        )
        if conductivity is None:
            default_k = hydraulic_view.conductivity.default_value
            if default_k is not None:
                conductivity = float(default_k)
            elif mapped_conductivity is not None:
                conductivity = float(mapped_conductivity[cell_index])
            else:
                raise ValueError(
                    "Boussinesq requires hydraulic_conductivity_m_s for every cell; "
                    f"cannot complete missing value on cell_id={int(bundle_cell.cell_id)}."
                )

        storage = (
            float(mapped_storage[cell_index])
            if mapped_storage is not None
            else bundle_cell.storage_coefficient
        )
        if storage is None:
            default_storage = hydraulic_view.storage_coefficient.default_value
            if default_storage is not None:
                storage = float(default_storage)
            elif mapped_storage is not None:
                storage = float(mapped_storage[cell_index])
            elif regime == "steady":
                storage = 0.0
            else:
                raise ValueError(
                    "Boussinesq requires storage_coefficient for every cell; "
                    "provide one bundle default, a flow Sy parameter, or per-cell "
                    f"bundle values. Missing value on cell_id={int(bundle_cell.cell_id)}."
                )

        completed_cells.append(
            replace(
                bundle_cell,
                hydraulic_conductivity_m_s=float(conductivity),
                storage_coefficient=float(storage),
            )
        )

    completed_bundle = replace(bundle, cells=tuple(completed_cells))
    return BoussinesqMesh.from_bundle(completed_bundle)


class BoussinesqFlowAdapter:
    """Bridge one planned ``flow/boussinesq`` run to the local solver API."""

    process_type = "flow"
    solver_name = "boussinesq"

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one Boussinesq flow run."""
        state = ctx.state
        mesh_bundle = None
        try:
            solver_mesh = _resolve_runtime_solver_mesh(state.setup)
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
            mesh_bundle = _resolve_mesh_bundle(state.setup)
            solver_mesh = _resolve_bundle_solver_mesh(state.setup, bundle=mesh_bundle)
        runtime_mesh_support = getattr(state.setup, "mesh_support", None)
        if runtime_mesh_support is not None:
            solver_mesh = replace(
                solver_mesh,
                support_metadata=runtime_mesh_support,
            )
        workspace = getattr(state.setup, "workspace", None)
        model_folder = (
            Path(workspace.solver_scratch_folder) if workspace is not None else Path.cwd()
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
            try:
                model.post_processing()
            except Exception:
                pass
            raise RuntimeError(
                f"Flow solver 'boussinesq' failed for run '{ctx.run.id}'. "
                f"See {getattr(model, 'full_path', '<unknown>')} for diagnostics."
            )

        # Serialize state and summary so the BoussinesqOutputAdapter can
        # extract them into the SimulationCatalog (same lifecycle as MODFLOW
        # writing .hds/.cbc that its adapter then reads).
        model.post_processing()

        return RunExecutionResult(
            primary_model=model,
            solver_output_dir=Path(model.full_path) if hasattr(model, "full_path") else None,
        )


__all__ = ["BoussinesqFlowAdapter"]
