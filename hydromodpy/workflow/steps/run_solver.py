"""Run-solver step - execute the plan and record solver output locations."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import OpenStoreState, PipelineState, SolverRanState

if TYPE_CHECKING:
    from hydromodpy.workflow.launcher_protocol import Launcher

logger = get_logger(__name__)


class RunSolverStep:
    """Execute the plan via the configured launcher."""

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

    def __init__(self, launcher: Launcher | None = None) -> None:
        self.launcher = launcher

    def artifacts(self, state: PipelineState) -> tuple[str, ...]:
        """Return workspace-relative paths produced by the solver run."""
        from hydromodpy.workflow.steps.prepare_solver import _store_sim_artifacts

        ctx = state.get("ctx")
        if ctx is None:
            return ()
        sim_id = getattr(ctx, "sim_id", None)
        if not sim_id:
            return ()
        return _store_sim_artifacts(ctx, sim_id)

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.simulation.execution.runner import (
            ProcessCallbacks,
            SimulationRunner,
        )
        from hydromodpy.simulation.extraction.post_run import record_run_execution_metrics
        from hydromodpy.simulation.planning.plan import RunContext

        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("RunSolverStep requires 'ctx' in state.data")

        plan = ctx.execution.simulation_plan
        if plan is None:
            raise ConfigError("run_solver step requires execution.simulation_plan to be set")

        callbacks = ProcessCallbacks(
            after_process=state.get("after_process"),
            after_run=None,
        )

        t0 = time.monotonic()
        launcher = self.launcher if self.launcher is not None else SimulationRunner()
        executed_results = launcher.execute(plan, ctx, callbacks=callbacks) or ()
        for run, result in executed_results:
            record_run_execution_metrics(
                ctx=RunContext(plan=plan, run=run, state=ctx),
                sim_id=ctx.sim_id,
                store=ctx.store,
                result=result,
            )
        wall_seconds = time.monotonic() - t0

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            wall_seconds=wall_seconds,
        )
