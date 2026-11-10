"""Run-solver step - execute the plan, record solver output locations and the time of each solve.

The time of a solve is no result of the run: the step adds one ``solve`` line per
solved run of the plan to ``profile.json``, from ``SolverRun.solve_s``, and writes
no duration to the metrics, the facts or the seal.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.stopwatch import Measure, max_rss_mb
from hydromodpy.workflow.record.run_store import run_is_persisted, run_store
from hydromodpy.workflow.state import PipelineState

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.solver.base.plan import SolverRun
    from hydromodpy.solver.base.runner import SimulationRunner

logger = get_logger(__name__)


def _resumed_solver_runs(ctx: WorkflowContext, folders: Mapping[str, str]) -> dict[str, SolverRun]:
    """Put back the ``SolverRun`` of each run the facts of an earlier attempt name a folder for.

    The run was solved, so its input files are on disk and ``written`` and
    ``solved`` are true. The slot is the folder the solver wrote in, cut into its
    parent and its name. The ``Model`` is the one the resumed prepare-solver step
    built again, and the options are read from the configuration as the runner
    reads them. The solver model is not rebuilt.
    """
    from hydromodpy.solver.base.plan import RunSlot, SolverRun
    from hydromodpy.solver.base.registry import solvers
    from hydromodpy.solver.base.runner import options_for

    plan = ctx.execution.simulation_plan
    planned = {run.id: run for run in (() if plan is None else plan.runs)}
    resumed: dict[str, SolverRun] = {}
    for run_id, folder in folders.items():
        run = planned.get(run_id)
        options = None
        if run is not None and run.is_solver_backed:
            options = options_for(solvers.create(run.process_type, run.solver), run, ctx.cfg)
        path = Path(folder)
        resumed[run_id] = SolverRun(
            slot=RunSlot(folder=path.parent, name=path.name),
            model=getattr(ctx.setup, "model", None),
            options=options,
            output_dir=path,
            written=True,
            solved=True,
        )
    return resumed


def _record_solves(
    ctx: WorkflowContext, executed: Iterable[tuple[Any, SolverRun]], step_started_at: datetime
) -> None:
    """Add one ``solve`` line to the profile for each run of the plan that solved.

    The backend measures the duration around the call that solves and not the
    instant it began, so the line starts where the previous solve of the plan ended,
    counted from the start of the step. The memory is the peak of the process now.
    """
    from hydromodpy.workflow.runner import record_measure

    started_at = step_started_at
    for run, result in executed:
        if result.solve_s is None:
            continue
        record_measure(
            ctx.run_dir,
            Measure(
                kind="solve",
                name=str(run.id),
                started_at=started_at,
                duration_s=result.solve_s,
                max_rss_mb=max_rss_mb(),
            ),
            attempt=ctx.attempt,
        )
        started_at += timedelta(seconds=result.solve_s)


class RunSolverStep:
    """Execute the plan via the configured launcher."""

    name = "run_solver"
    reads: ClassVar[tuple[str, ...]] = (
        "after_process",
        "ctx",
    )
    writes: ClassVar[tuple[str, ...]] = ("ctx",)
    config_sections: ClassVar[tuple[str, ...]] = (
        "flow",
        "transport",
        "solver",
    )

    def __init__(self, launcher: SimulationRunner | None = None) -> None:
        self.launcher = launcher

    def depends_on(self) -> tuple[str, ...]:
        return ("prepare_solver",)

    def artifacts(self, state: PipelineState) -> tuple[str, ...]:
        """Return workspace-relative paths produced by the solver run."""
        from hydromodpy.workflow.steps.prepare_solver.facts import store_sim_artifacts

        ctx = state.get("ctx")
        if ctx is None or not run_is_persisted(ctx):
            return ()
        sim_id = getattr(ctx, "sim_id", None)
        if not sim_id or getattr(ctx, "run_dir", None) is None:
            return ()
        with run_store(ctx) as store:
            return store_sim_artifacts(ctx, sim_id, store=store)

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        """Rebuild the state without re-running the solver.

        The folder each run of the plan solved in is read back from the facts of
        the run: the extract step that resumes reads the solver outputs there. Each run gets a ``SolverRun`` put back in
        ``execution.solver_runs``, solved and written, with its ``Model`` and its
        options and without a solver model: downstream steps (extract, derive,
        export) read the Zarr store and the solver folder and need no live solver
        object.
        """
        ctx = prior_state.get("ctx")
        if ctx is None:
            raise ConfigError("RunSolverStep.rebuild_state requires 'ctx' in state.data")
        sim_id = getattr(ctx, "sim_id", None)
        if sim_id is not None and run_is_persisted(ctx) and getattr(ctx, "run_dir", None):
            with run_store(ctx) as store:
                ctx.execution.solver_runs.update(
                    _resumed_solver_runs(ctx, store.facts.solver_output_dirs)
                )
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.solver.base.plan import RunContext
        from hydromodpy.solver.base.runner import ProcessCallbacks, SimulationRunner
        from hydromodpy.workflow.steps.prepare_solver.dispatch import refresh_run_environment
        from hydromodpy.workflow.steps.run_outputs import (
            record_run_execution_metrics,
            record_what_the_model_says,
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

        started_at = datetime.now(UTC)
        launcher = self.launcher if self.launcher is not None else SimulationRunner()
        if run_is_persisted(ctx):
            # One handle for the whole solve: the products of every executed run
            # are written through it, and the folder each run solved in is read
            # back to the facts, for the derive step and for a resume.
            with run_store(ctx) as store:
                executed_results = launcher.execute(plan, ctx, callbacks=callbacks) or ()
                for run, result in executed_results:
                    record_run_execution_metrics(
                        ctx=RunContext.of(ctx, plan=plan, run=run, store=store),
                        sim_id=ctx.sim_id,
                        store=store,
                        result=result,
                    )
                    if result.output_dir is not None:
                        store.facts.solver_output_dirs[str(run.id)] = str(result.output_dir)
                refresh_run_environment(ctx, store=store)
                _record_solves(ctx, executed_results, started_at)
                for run, _result in executed_results:
                    record_what_the_model_says(
                        ctx=RunContext.of(ctx, plan=plan, run=run, store=store),
                        sim_id=ctx.sim_id,
                        store=store,
                    )
        else:
            launcher.execute(plan, ctx, callbacks=callbacks)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
