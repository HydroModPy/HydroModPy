"""Step 10 - export run artefacts and finalize the store.

Saves the config snapshot + capability gallery via
:func:`step_save_run_artifacts` and closes the ``SimulationCatalog``
via :func:`step_finalize_store`.

Inputs
------
``ctx`` : WorkflowContext
``wall_seconds`` : float (optional, from ``RunSolverStep``)

Outputs
-------
``ctx`` : same context with ``store`` closed / finalized.
"""

from __future__ import annotations

from typing import ClassVar

from hydromodpy.workflow.internals.state import DerivedState, ExportedState, PipelineState


class ExportStep:
    """Save artefacts, finalize and close the catalog."""

    name = "export"
    tin: ClassVar[type] = DerivedState
    tout: ClassVar[type] = ExportedState
    config_sections: ClassVar[tuple[str, ...]] = ()

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.workflow.steps.result_ingestion import step_save_run_artifacts
        from hydromodpy.workflow.steps.store_lifecycle import step_finalize_store

        ctx = state.get("ctx")
        if ctx is None:
            raise ValueError("ExportStep requires 'ctx' in state.data")

        wall_seconds = float(state.get("wall_seconds", 0.0) or 0.0)

        if ctx.store is not None:
            step_save_run_artifacts(ctx, wall_seconds)
            step_finalize_store(ctx, wall_seconds=wall_seconds)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
