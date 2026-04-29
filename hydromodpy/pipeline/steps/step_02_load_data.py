"""Step 2 - load external forcing data.

Thin wrapper around :func:`hydromodpy.workflow.steps.data_loading.step_data_loading`.
Loads recharge, hydrometry, piezometry, geology, … via the data managers.

Inputs
------
``ctx`` : WorkflowContext (must be fully resolved with setup already populated)

Outputs
-------
``ctx`` : same context with ``loaded_data`` populated.
"""

from __future__ import annotations

from typing import ClassVar

from hydromodpy.workflow.internals.state import LoadedState, PipelineState, ResolvedState


class LoadDataStep:
    """Ingest external + custom data via data managers."""

    name = "load_data"
    tin: ClassVar[type] = ResolvedState
    tout: ClassVar[type] = LoadedState
    config_sections: ClassVar[tuple[str, ...]] = ("data",)

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.workflow.steps.data_loading import step_data_loading

        ctx = state.get("ctx")
        if ctx is None:
            raise ValueError("LoadDataStep requires 'ctx' in state.data")

        step_data_loading(ctx)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
