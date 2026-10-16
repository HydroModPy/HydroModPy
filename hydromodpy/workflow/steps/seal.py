"""Step 13 - the seal of a completed run.

The last step of a persisted run writes the seal from the store of the run:
``simulation.parquet``, ``parameters.parquet``, ``provenance.json``,
``inputs.json`` and ``manifest.json`` last, then ``README.md``. The metadata
views the ``[[export]]`` blocks ask for render the seal, so they are written
right after it (:func:`hydromodpy.workflow.steps.export.step_after_seal`).
The outcome is not touched here: the pipeline still writes the journal row
of this step and its checkpoint under ``<run>/.hmp/`` once it returns, and
the attempt protocol around the pipeline flips ``outcome.json`` to
``completed`` and removes ``<run>/.hmp/`` when it finds the seal. A run that
does not reach this step keeps its outcome as the attempt protocol wrote it.

Inputs
------
``ctx`` : WorkflowContext with ``run_dir`` and ``sim_id`` populated.
``wall_seconds`` : the duration of the solve, for the recap.

Outputs
-------
``ctx`` : unchanged; the run directory is sealed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.run_store import run_is_persisted, run_store
from hydromodpy.workflow.steps.export import step_after_seal

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext

logger = get_logger(__name__)


class SealStep:
    """Write the seal of the run; the attempt protocol closes the outcome after it."""

    name = "seal"
    reads: ClassVar[tuple[str, ...]] = ("ctx", "wall_seconds")
    writes: ClassVar[tuple[str, ...]] = ("ctx",)
    config_sections: ClassVar[tuple[str, ...]] = ()

    def depends_on(self) -> tuple[str, ...]:
        return ("export",)

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace,
        run_id: str,
    ) -> PipelineState:
        """Advance past a seal that is already on disk."""
        ctx: WorkflowContext | None = prior_state.get("ctx")
        if ctx is None:
            raise ConfigError("SealStep.rebuild_state requires 'ctx' in state.data")
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )

    def run(self, state: PipelineState) -> PipelineState:
        ctx: WorkflowContext | None = state.get("ctx")
        if ctx is None:
            raise ConfigError("SealStep requires 'ctx' in state.data")
        if ctx.sim_id is None or not run_is_persisted(ctx):
            logger.debug("SealStep: this run keeps no store to seal, skipping")
        else:
            with run_store(ctx) as store:
                record = seal_completed(store)
            logger.info("Run %s sealed: %s", record.run.name, ctx.run_dir)
            step_after_seal(ctx, wall_seconds=float(state.get("wall_seconds", 0.0) or 0.0))
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )


__all__ = ["SealStep"]
