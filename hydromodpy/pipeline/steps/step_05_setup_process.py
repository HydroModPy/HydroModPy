"""Step 5 — set up Flow / Transport / Particles processes.

The domain-level process objects (``Flow``, ``Transport`` …) are
materialized lazily by ``SimulationRunner`` via the helpers
``ensure_flow``/``ensure_transport``. In the pipeline they are hoisted
here so the state after this step has all runtime process components
bound to the mesh.

Inputs
------
``ctx`` : WorkflowContext

Outputs
-------
``ctx`` : same context with ``setup.flow`` / ``setup.transport``
attached when the underlying config requests them.
"""

from __future__ import annotations

from typing import ClassVar

from hydromodpy.pipeline.state import MeshedState, PipelineState, SetupState


class SetupProcessStep:
    """Instantiate flow / transport process objects bound to the domain."""

    name = "setup_process"
    tin: ClassVar[type] = MeshedState
    tout: ClassVar[type] = SetupState

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.simulation import ensure_flow, ensure_transport

        ctx = state.get("ctx")
        if ctx is None:
            raise ValueError("SetupProcessStep requires 'ctx' in state.data")

        if getattr(ctx.setup, "domain", None) is not None:
            flow_cfg = getattr(ctx.cfg, "flow", None)
            if flow_cfg is not None:
                ensure_flow(ctx)
            transport_cfg = getattr(ctx.cfg, "transport", None)
            if transport_cfg is not None:
                ensure_transport(ctx)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
