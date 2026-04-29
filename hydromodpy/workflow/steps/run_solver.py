"""Run-solver step - execute the plan and ingest run results into the store."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import OpenStoreState, PipelineState, SolverRanState

if TYPE_CHECKING:
    from hydromodpy.simulation.planning.plan import ProcessRun, RunExecutionResult
    from hydromodpy.workflow.context import WorkflowContext

logger = get_logger(__name__)


def step_ingest_run_results(
    ctx: WorkflowContext,
    run: ProcessRun,
    result: RunExecutionResult,
) -> None:
    """Ingest solver outputs into ``ctx.store`` after one run completes."""
    if ctx.store is None:
        return

    from hydromodpy.simulation.extraction.post_run import post_run_results
    from hydromodpy.simulation.planning.plan import RunContext

    plan = ctx.execution.simulation_plan
    results_cfg = ctx.cfg.simulation.results
    post_run_results(
        ctx=RunContext(plan=plan, run=run, state=ctx),
        sim_id=ctx.sim_id,
        results_config=results_cfg,
        store=ctx.store,
        keep_solver_files=True,
        run_id=ctx.setup.run_id,
    )


class RunSolverStep:
    """Execute the plan and ingest results via ``SimulationRunner``."""

    name = "run_solver"
    tin: ClassVar[type] = OpenStoreState
    tout: ClassVar[type] = SolverRanState
    config_sections: ClassVar[tuple[str, ...]] = (
        "flow",
        "transport",
        "solver",
        "modflownwt",
        "modflow6",
    )

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.simulation.execution.runner import (
            ProcessCallbacks,
            SimulationRunner,
        )

        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("RunSolverStep requires 'ctx' in state.data")

        plan = ctx.execution.simulation_plan
        if plan is None:
            raise ConfigError("run_solver step requires execution.simulation_plan to be set")

        if ctx.execution.lightweight:
            after_run = None
        else:

            def after_run(run, result, st):
                step_ingest_run_results(ctx, run, result)

        callbacks = ProcessCallbacks(
            after_process=state.get("after_process"),
            after_run=after_run,
        )

        t0 = time.monotonic()
        SimulationRunner(callbacks=callbacks).execute(plan, ctx)
        wall_seconds = time.monotonic() - t0

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            wall_seconds=wall_seconds,
        )
