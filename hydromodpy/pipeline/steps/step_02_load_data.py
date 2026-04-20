"""Step 2 — load external forcing data.

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

from hydromodpy.pipeline.state import PipelineState


class LoadDataStep:
    """Ingest external + custom data via data managers."""

    name = "load_data"

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.workflow.steps.data_loading import step_data_loading

        ctx = state.get("ctx")
        if ctx is None:
            raise ValueError("LoadDataStep requires 'ctx' in state.data")

        # Only call the underlying loader if setup has produced a domain;
        # otherwise leave the step as a no-op so the pipeline can be run
        # on partially configured contexts (e.g. unit tests).
        if getattr(ctx.setup, "domain", None) is not None:
            step_data_loading(ctx)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
