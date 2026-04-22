"""Step 3 — build the geographic runtime and spatial supports (setup phase).

Wraps the geographic portion of ``step_setup`` + the ``setup`` phase of
``step_spatial_supports``. After this step, ``ctx.setup.geographic`` is
populated and catchment zones are bound to the domain.

Inputs
------
``ctx`` : WorkflowContext

Outputs
-------
``ctx`` : same context with ``setup.geographic`` and ``setup.domain``
populated.
"""

from __future__ import annotations

from typing import ClassVar

from hydromodpy.pipeline.state import LoadedState, MeshedState, PipelineState


class BuildGeographicStep:
    """Build geographic runtime, domain, and setup-phase spatial supports."""

    name = "build_geographic"
    tin: ClassVar[type] = LoadedState
    tout: ClassVar[type] = MeshedState

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.workflow.steps.setup import step_setup
        from hydromodpy.workflow.steps.spatial_supports import step_spatial_supports

        ctx = state.get("ctx")
        if ctx is None:
            raise ValueError("BuildGeographicStep requires 'ctx' in state.data")

        requested_supports = state.get("requested_domain_supports") or {}
        requested_support_ids = state.get("requested_spatial_support_ids", ())
        registry = state.get("spatial_support_registry")

        step_setup(
            ctx,
            requested_spatial_support_ids=requested_support_ids,
            requested_domain_supports=requested_supports,
        )
        step_spatial_supports(
            ctx,
            phase="setup",
            requested_domain_supports=requested_supports,
            registry=registry,
        )

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
