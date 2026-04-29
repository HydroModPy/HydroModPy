"""Step 8 - finalize solver result extraction.

Result ingestion (Zarr writes for head / budget / timeseries) happens
run-by-run via the ``after_run`` callback installed by
:class:`RunSolverStep`. This step is therefore a no-op in the default
pipeline, but it is kept as a distinct step so future solver-specific
post-extraction can be hooked here and so the pipeline matches the
canonical 11-step sequence.

Inputs
------
``ctx`` : WorkflowContext

Outputs
-------
``ctx`` : unchanged (pass-through).
"""

from __future__ import annotations

from typing import ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.internals.state import ExtractedState, PipelineState, SolverRanState


class ExtractStep:
    """Finalize extraction (currently a pass-through after run-time ingestion)."""

    name = "extract"
    tin: ClassVar[type] = SolverRanState
    tout: ClassVar[type] = ExtractedState
    config_sections: ClassVar[tuple[str, ...]] = ()

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("ExtractStep requires 'ctx' in state.data")
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
