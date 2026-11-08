"""Step 9 - what a run derives once its fields are in the store.

Every derived field is rebuilt on read, so this step writes none. It runs
:func:`~hydromodpy.workflow.steps.run_outputs.derive_run_outputs` for each
solver-backed run: the discharge band of the drains and the catchment
aggregates. It writes the simulated series of each observed station
(:func:`~hydromodpy.calibration.runners.promotion.write_station_series`) and
samples the points declared in ``[observation]``
(:func:`~hydromodpy.results.run.observation_points.sample_observation_points`).
Then it scores the run under
its metric rule (:func:`~hydromodpy.results.fit_metrics.fit_metrics`,
``[metrics] window`` at ``[metrics] station``, default ``[site] gauge``) and
puts the rows and the headline NSE in the facts the seal reads. The score
comes after the aggregates because the catchment discharge is one of them.

Inputs
------
``ctx`` : WorkflowContext with ``sim_id`` populated.

Outputs
-------
``ctx`` : unchanged; the store gains the rows above as a side effect.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.results.fit_metrics import score_run_under_its_rule
from hydromodpy.results.run.observation_points import sample_declared_points
from hydromodpy.workflow.record.run_store import run_is_persisted, run_store
from hydromodpy.workflow.state import PipelineState

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext

logger = get_logger(__name__)


class DeriveStep:
    """Write the catchment aggregates, observation samples and the scores of the run."""

    name = "derive"
    reads: ClassVar[tuple[str, ...]] = ("ctx", "station_outputs")
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
        if sim_id is None or not run_is_persisted(ctx):
            logger.debug("DeriveStep: this run keeps no store to derive into, skipping")
            return state.advance(
                step_index=state.step_index + 1,
                step_name=self.name,
                ctx=ctx,
            )

        from hydromodpy.calibration.runners.promotion import write_station_series

        with run_store(ctx) as store:
            write_station_series(ctx, store=store, outputs=state.get("station_outputs"))

        # Solver models are consumed up to here (provenance backfill, calibration
        # trial metrics, the station series). Past
        # this point they are dead weight: a transient flopy model carries the
        # full stress-period data, which reaches GBs on multi-thousand-period
        # runs. Release them before the derive phase allocates.
        runs = ctx.execution.solver_runs
        runs.update({run_id: replace(run, solver_model=None) for run_id, run in runs.items()})

        plan = ctx.execution.simulation_plan
        if plan is not None:
            from hydromodpy.solver.base.plan import RunContext
            from hydromodpy.workflow.steps.run_outputs import derive_run_outputs

            with run_store(ctx) as store:
                for run in plan.runs:
                    if not run.is_solver_backed:
                        continue
                    derive_run_outputs(
                        ctx=RunContext.of(ctx, plan=plan, run=run, store=store),
                        store=store,
                    )
                sample_declared_points(ctx.cfg, store=store)
                score_run_under_its_rule(ctx.cfg, store=store)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
