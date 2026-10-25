"""Step 9 - what a run derives once its fields are in the store.

Every derived field is rebuilt on read, so this step writes none. It runs
:func:`~hydromodpy.simulation.extraction.post_run.derive_run_outputs` for each
solver-backed run: the discharge band of the drains and the catchment
aggregates. It samples the points declared in ``[observation]``
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

from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.run_store import run_is_persisted, run_store

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.results.storage.run_store import RunStore

logger = get_logger(__name__)


def sample_declared_points(ctx: WorkflowContext, *, store: RunStore) -> int:
    """Sample the ``[observation]`` points while the run still holds its fields.

    A point known in advance costs nothing to read later: its series lands in
    the timeseries table of the run and its declaration in
    ``observation_points.parquet``. A failure is logged, never fatal: the
    results of the run are already in.
    """
    from hydromodpy.results.run.observation_points import sample_observation_points

    observation = getattr(ctx.cfg, "observation", None)
    declarations = observation.declarations() if observation is not None else []
    if not declarations:
        return 0
    try:
        return sample_observation_points(store, store.sim_id, declarations)
    except Exception:
        logger.warning("Could not sample the declared observation points", exc_info=True)
        return 0


def score_run_under_its_rule(ctx: WorkflowContext, *, store: RunStore) -> None:
    """Score the series of the run against its observations and record the result.

    The rows go to the metrics of the facts, the NSE at the rule station to
    their headline score, both sealed by the record. An observed gauge that
    meets no simulated series fails the non-fatal check
    :data:`~hydromodpy.results.fit_metrics.UNSCORED_OBSERVATIONS_CHECK`, which
    the README of the run prints. A score that cannot be
    computed is logged and the run keeps its results: the seal says
    ``nse = NULL`` and the table says why.
    """
    from hydromodpy.results.fit_metrics import UNSCORED_OBSERVATIONS_CHECK, fit_metrics
    from hydromodpy.results.metric_rule import MetricRule

    site = store.facts.site
    rule = MetricRule.from_config(ctx.cfg, gauge=None if site is None else site.gauge)
    try:
        scores = fit_metrics(store.run_dir, rule=rule, period_start=store.facts.period_start)
    except Exception:
        logger.warning("Could not score the run against its observations", exc_info=True)
        return
    for row in scores.rows:
        store.facts.put_metric(row)
    store.facts.score = scores.score
    message = scores.unscored_message()
    if message is not None:
        store.facts.note_validity(
            UNSCORED_OBSERVATIONS_CHECK, False, float(len(scores.unscored)), message
        )


class DeriveStep:
    """Write the catchment aggregates, observation samples and the scores of the run."""

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
        if sim_id is None or not run_is_persisted(ctx):
            logger.debug("DeriveStep: this run keeps no store to derive into, skipping")
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
            with run_store(ctx) as store:
                for run in plan.runs:
                    if not run.is_solver_backed:
                        continue
                    derive_run_outputs(
                        ctx=RunContext.of(ctx, plan=plan, run=run, store=store),
                        sim_id=sim_id,
                        results_config=results_cfg,
                        store=store,
                    )
                sample_declared_points(ctx, store=store)
                score_run_under_its_rule(ctx, store=store)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
