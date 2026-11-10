"""``PrepareSolverStep``: plans the simulation and opens the run it will execute.

The work is spread over sibling modules. :mod:`model` freezes the ``Flow`` into the
``Model`` the solver reads, :mod:`prepare` and :mod:`forcings` persist the inputs,
:mod:`freeze` the frozen configuration, :mod:`facts` the facts of the run and
:mod:`dispatch` binds the pipeline to its run directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.workflow.products import write_products
from hydromodpy.workflow.record.run_store import run_is_persisted, run_store
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.prepare_solver.dispatch import (
    bind_run_directory,
    initial_facts,
    step_open_run,
)
from hydromodpy.workflow.steps.prepare_solver.facts import store_sim_artifacts
from hydromodpy.workflow.steps.prepare_solver.forcings import step_persist_forcings
from hydromodpy.workflow.steps.prepare_solver.model import step_build_model
from hydromodpy.workflow.steps.prepare_solver.prepare import (
    step_persist_params,
    step_write_provenance,
)

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext

logger = get_logger(__name__)


def _resolve_plan_and_results(ctx, *, store=None) -> None:
    """Populate the simulation plan and the per-cell budget the run keeps.

    The plan is a deterministic derivation of the config. The budget policy
    is decided once, at planning: a resumed run whose store already says what
    its extraction kept (the ``budget/`` attributes) takes it from there.
    ``store`` is the open store of a resume; a fresh run passes none.
    """
    from hydromodpy.solver.base.planner import SimulationPlanner
    from hydromodpy.workflow.steps.planning import step_configure_results

    if ctx.execution.simulation_plan is None:
        sim_cfg = getattr(ctx.cfg, "simulation", None)
        if sim_cfg is not None:
            ctx.execution.simulation_plan = SimulationPlanner().build(sim_cfg)

    if ctx.execution.simulation_plan is None:
        return
    stored = _stored_budget_keep(ctx, store) if store is not None else None
    if stored is not None:
        ctx.budget_terms = stored
        return
    ctx.budget_terms = step_configure_results(
        ctx.cfg.simulation.results,
        ctx.execution.simulation_plan,
        ctx.cfg.display,
        display_active=not ctx.execution.lightweight,
        export_requests=ctx.cfg.export,
        calibration=ctx.cfg.calibration,
        observation=ctx.cfg.observation,
        lightweight=ctx.execution.lightweight,
    )


def _stored_budget_keep(ctx: WorkflowContext, store) -> BudgetKeep | None:
    """Return the budget policy the store of ``ctx`` declares, or None."""
    from hydromodpy.core.budget.terms import POLICY_ALL, kept_budget

    sim_id = ctx.sim_id
    if sim_id is None or not store.fields_path_for(sim_id).exists():
        return None
    sim_zarr = store.open_zarr(sim_id)
    try:
        kept = kept_budget(sim_zarr.root)
    finally:
        sim_zarr.close()
    if kept is None:
        return None
    if kept.policy == POLICY_ALL:
        return BudgetKeep.everything()
    return BudgetKeep.of_terms(kept.terms)


class PrepareSolverStep:
    """Build the simulation plan, open the run it will execute and build its ``Model``.

    Composed from sibling modules: :mod:`model` (the frozen ``Model``),
    :mod:`prepare` (writes inputs), :mod:`facts` (introspection) and
    :mod:`dispatch` (binding).

    Every write goes through a store this step opens and closes itself, so
    the handle is gone by the time the next step starts.
    """

    name = "prepare_solver"
    reads: ClassVar[tuple[str, ...]] = (
        "calibrated_by",
        "ctx",
        "lineage",
        "promotion",
        "run_dir",
        "run_overrides",
        "solution_key",
    )
    writes: ClassVar[tuple[str, ...]] = ("ctx",)
    config_sections: ClassVar[tuple[str, ...]] = (
        "flow",
        "transport",
        "solver",
    )

    def depends_on(self) -> tuple[str, ...]:
        return ("setup_process",)

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("PrepareSolverStep requires 'ctx' in state.data")

        _resolve_plan_and_results(ctx)
        # The data step may have bound new forcings to the flow since the last run
        # of this context, so the model of that run is not this run's.
        ctx.setup.model = None

        if run_is_persisted(ctx):
            bind_run_directory(
                ctx,
                run_dir=state.get("run_dir"),
                lineage=state.get("lineage"),
                calibrated_by=state.get("calibrated_by"),
                run_overrides=state.get("run_overrides"),
            )
            write_products(ctx)
            workspace = ctx.setup.workspace
            persistence = ctx.cfg.simulation.results.persistence
            facts = initial_facts(ctx, solution_key=state.get("solution_key"))
            # A promoted run carries what its session says about it.
            promotion = state.get("promotion")
            if promotion is not None:
                facts.apply_promotion(promotion)
            with RunStore.open(
                ctx.run_dir,
                facts=facts,
                persistence=persistence,
                workspace=None if workspace is None else workspace.project_root,
            ) as store:
                step_open_run(ctx, store=store)
                model = step_build_model(ctx, store=store)
                if model is not None:
                    step_persist_params(
                        store, ctx.sim_id, model.properties.profiles, domain=model.geometry.domain
                    )
                step_write_provenance(ctx, store=store)
                step_persist_forcings(ctx, store=store)
        else:
            step_build_model(ctx)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )

    def artifacts(self, state: PipelineState) -> tuple[str, ...]:
        """Return workspace-relative paths persisted by this step."""
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
        """Recover the identity of the run a previous attempt opened.

        The plan is a pure function of the config, so it is recomputed here.
        The run directory is the one the state carries; the outcome it holds
        names the run, and the per-cell budget policy is read back from the
        store when the extraction already wrote it. The ``Model`` is built again,
        because a resume at ``run_solver`` has none in memory.
        """
        ctx = prior_state.get("ctx")
        if ctx is None:
            raise ConfigError("PrepareSolverStep.rebuild_state requires 'ctx' in state.data")

        ws = getattr(getattr(ctx, "setup", None), "workspace", None)
        if ws is None:
            raise ConfigError(
                "PrepareSolverStep.rebuild_state requires a resolved workspace on the context"
            )

        if not run_is_persisted(ctx):
            _resolve_plan_and_results(ctx)
            step_build_model(ctx)
        else:
            run_dir = prior_state.get("run_dir") or getattr(ctx, "run_dir", None)
            if run_dir is None:
                raise ConfigError(
                    f"resume: the state names no run directory for {run_id!r}; "
                    "cannot rebuild the run state."
                )
            outcome = read_outcome(Path(run_dir))
            if outcome is None:
                raise ConfigError(f"resume: {run_dir} carries no outcome; nothing to resume.")
            ctx.run_dir = Path(run_dir)
            ctx.sim_id = outcome.sim_id
            ctx.attempt = outcome.attempt
            write_products(ctx)
            with run_store(ctx) as store:
                _resolve_plan_and_results(ctx, store=store)
                step_build_model(ctx, store=store)

        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )


__all__ = ("PrepareSolverStep",)
