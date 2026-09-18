"""Run-solver step - execute the plan and record solver output locations."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import OpenStoreState, PipelineState, SolverRanState
from hydromodpy.workflow.run_catalog import run_catalog, run_is_catalogued

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

    def depends_on(self) -> tuple[str, ...]:
        return ("prepare_solver",)

    def artifacts(self, state: PipelineState) -> tuple[str, ...]:
        """Return workspace-relative paths produced by the solver run."""
        from hydromodpy.workflow.steps.prepare_solver import _store_sim_artifacts

        ctx = state.get("ctx")
        if ctx is None or not run_is_catalogued(ctx):
            return ()
        sim_id = getattr(ctx, "sim_id", None)
        if not sim_id:
            return ()
        with run_catalog(ctx) as store:
            return _store_sim_artifacts(ctx, sim_id, store=store)

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        """Rebuild the state without re-running the solver.

        Reads ``runs_environment.duration_s`` from the catalog to restore
        ``wall_seconds``. ``solver_result`` stays ``None``: downstream steps
        (extract, derive, export) read directly from the Zarr / solver
        workdir and do not need a live :class:`RunResult` object.
        """
        ctx = prior_state.get("ctx")
        if ctx is None:
            raise ConfigError("RunSolverStep.rebuild_state requires 'ctx' in state.data")
        wall_seconds: float | None = None
        sim_id = getattr(ctx, "sim_id", None)
        if sim_id is not None and run_is_catalogued(ctx):
            with run_catalog(ctx) as store:
                try:
                    row = store.backend.fetch_one(
                        "SELECT duration_s FROM runs_environment WHERE sim_id = ? "
                        "ORDER BY recorded_at DESC LIMIT 1",
                        [sim_id],
                    )
                except Exception:
                    row = None
            if row is not None and row[0] is not None:
                wall_seconds = float(row[0])
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            wall_seconds=wall_seconds,
        )

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.core.state.run_state import RunState
        from hydromodpy.simulation.execution.runner import (
            ProcessCallbacks,
            SimulationRunner,
        )
        from hydromodpy.simulation.extraction.post_run import record_run_execution_metrics
        from hydromodpy.simulation.planning.plan import RunContext
        from hydromodpy.workflow.steps.prepare_solver.dispatch import refresh_run_environment

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
        if run_is_catalogued(ctx):
            # One handle for the whole solve: the adapters reach the run's
            # catalog through the ``RunContext`` the launcher builds, and the
            # metrics of every executed run are written before it closes.
            with run_catalog(ctx) as store:
                executed_results = (
                    launcher.execute(plan, ctx, callbacks=callbacks, store=store) or ()
                )
                for run, result in executed_results:
                    record_run_execution_metrics(
                        ctx=RunContext(plan=plan, run=run, state=RunState.of(ctx), store=store),
                        sim_id=ctx.sim_id,
                        store=store,
                        result=result,
                    )
                refresh_run_environment(ctx, store=store)
        else:
            launcher.execute(plan, ctx, callbacks=callbacks)
        wall_seconds = time.monotonic() - t0

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            wall_seconds=wall_seconds,
        )
