"""Step 7 - run the simulation plan via ``SimulationRunner``.

Executes every ``ProcessRun`` of the plan via its solver adapter. After
each run, :func:`step_ingest_run_results` is invoked to post-process
the solver output into the store.

Inputs
------
``ctx`` : WorkflowContext (with ``execution.simulation_plan`` set and
``store`` opened)

Outputs
-------
``ctx`` : same context with each ``ProcessRun`` result stored in
``ctx.execution.models_by_run_id``.
``wall_seconds`` : float (elapsed solver time)
"""

from __future__ import annotations

import time
from typing import ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.internals.state import OpenStoreState, PipelineState, SolverRanState


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
        from hydromodpy.workflow.steps.result_ingestion import step_ingest_run_results

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
