"""Step 4 - build or load the hydrological mesh.

Wraps ``step_mesh`` (embedded catchment mesh) + ``step_mesh_input``
(external pre-computed mesh) + the ``data`` phase of
``step_spatial_supports`` (supports that require the mesh / fresh data).

Inputs
------
``ctx`` : WorkflowContext

Outputs
-------
``ctx`` : same context with ``setup.mesh`` populated.
"""

from __future__ import annotations

from typing import ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.internals.state import MeshedState, PipelineState


class BuildMeshStep:
    """Build / import the mesh and complete the spatial supports."""

    name = "build_mesh"
    tin: ClassVar[type] = MeshedState
    tout: ClassVar[type] = MeshedState
    config_sections: ClassVar[tuple[str, ...]] = ("domain.supports",)

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.workflow.steps.mesh import step_mesh, step_mesh_input
        from hydromodpy.workflow.steps.spatial_supports import step_spatial_supports

        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("BuildMeshStep requires 'ctx' in state.data")

        requested_supports = state.get("requested_domain_supports") or {}
        registry = state.get("spatial_support_registry")

        step_spatial_supports(
            ctx,
            phase="data",
            requested_domain_supports=requested_supports,
            registry=registry,
        )
        step_mesh(
            ctx,
            mesh_section_data=state.get("mesh_section_data"),
            constraints_mode=state.get("constraints_mode"),
        )
        step_mesh_input(ctx, external_mesh_input=state.get("external_mesh_input"))

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
