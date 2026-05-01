"""Run-solver step - execute the plan and record solver output locations."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import OpenStoreState, PipelineState, SolverRanState

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class RunSolverStep:
    """Execute the plan via ``SimulationRunner``."""

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

        callbacks = ProcessCallbacks(
            after_process=state.get("after_process"),
            after_run=None,
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
