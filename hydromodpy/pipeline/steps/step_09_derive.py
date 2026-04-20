"""Step 9 — derived fields (watertable, seepage, flux).

Derived-field computation is currently colocated with the solver-
specific postprocessors invoked inside ``step_ingest_run_results``.
This step exists to preserve the canonical 11-step ordering and to
provide a single injection point for future ``DerivedComputer``
registrations (see architecture cible §3.10).

Inputs
------
``ctx`` : WorkflowContext

Outputs
-------
``ctx`` : unchanged.
"""

from __future__ import annotations

from hydromodpy.pipeline.state import PipelineState


class DeriveStep:
    """Compute derived fields (placeholder — delegated to extractors for now)."""

    name = "derive"

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ValueError("DeriveStep requires 'ctx' in state.data")
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
