"""Step 9 - what a run derives once its fields are in the store.

Every derived field is rebuilt on read, so this step writes none. It runs
:func:`~hydromodpy.simulation.extraction.post_run.derive_run_outputs` for each
solver-backed run: the discharge band of the drains, the catchment
aggregates, the declared observation points and the fit metrics.

Inputs
------
``ctx`` : WorkflowContext with ``sim_id`` populated.

Outputs
-------
``ctx`` : unchanged; the store gains the rows above as a side effect.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.run_catalog import run_catalog, run_is_catalogued

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext

logger = get_logger(__name__)


class DeriveStep:
    """Write the catchment aggregates, observation samples and fit metrics."""

    name = "derive"
    reads: ClassVar[tuple[str, ...]] = ("ctx",)
    writes: ClassVar[tuple[str, ...]] = ("ctx",)
    config_sections: ClassVar[tuple[str, ...]] = ("postprocess",)

    def depends_on(self) -> tuple[str, ...]:
        return ("extract",)

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace,
        run_id: str,
    ) -> PipelineState:
        """Advance past a derive phase whose rows are already in the store."""
        ctx: WorkflowContext | None = prior_state.get("ctx")
        if ctx is None:
            raise ConfigError("DeriveStep.rebuild_state requires 'ctx' in state.data")
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )

    def run(self, state: PipelineState) -> PipelineState:
        ctx: WorkflowContext | None = state.get("ctx")
        if ctx is None:
            raise ConfigError("DeriveStep requires 'ctx' in state.data")

        sim_id = getattr(ctx, "sim_id", None)
        if sim_id is None or not run_is_catalogued(ctx):
            logger.debug("DeriveStep: this run has no index to derive into, skipping")
            return state.advance(
                step_index=state.step_index + 1,
                step_name=self.name,
                ctx=ctx,
            )

        # Solver models are consumed up to extraction only (provenance backfill,
        # calibration trial metrics; trials cap the pipeline at extract). Past
        # this point they are dead weight: a transient flopy model carries the
        # full stress-period data, which reaches GBs on multi-thousand-period
        # runs. Release them before the derive phase allocates.
        ctx.execution.models_by_run_id.clear()

        plan = ctx.execution.simulation_plan
        if plan is not None:
            from hydromodpy.simulation.extraction.post_run import derive_run_outputs
            from hydromodpy.simulation.planning.plan import RunContext

            results_cfg = ctx.cfg.simulation.results
            with run_catalog(ctx) as store:
                for run in plan.runs:
                    if not run.is_solver_backed:
                        continue
                    derive_run_outputs(
                        ctx=RunContext.of(ctx, plan=plan, run=run, store=store),
                        sim_id=sim_id,
                        results_config=results_cfg,
                        store=store,
                    )

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
