"""Prepare-solver step decomposed into three concerns.

- :mod:`prepare` - persistence helpers (params, mesh, geographic,
  provenance, forcings).
- :mod:`validate` - pure validators and artifact discovery helpers
  (``_primary_solver_for_simulation``, ``collect_run_facts``,
  ``_store_sim_artifacts``).
- :mod:`dispatch` - binding the pipeline to its run directory and recording
  what the run was built from (``bind_run_directory``, ``step_open_run``).

The :class:`PrepareSolverStep` class itself sits in this ``__init__`` so
its public import path is preserved
(``from hydromodpy.workflow.steps.prepare_solver import PrepareSolverStep``).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.budget_terms import BudgetKeep
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.run_store import run_is_persisted, run_store
from hydromodpy.workflow.steps.prepare_solver.dispatch import (
    _register_tracked_input_files,
    bind_run_directory,
    initial_facts,
    step_open_run,
)
from hydromodpy.workflow.steps.prepare_solver.prepare import (
    step_persist_forcings,
    step_persist_geographic,
    step_persist_mesh,
    step_persist_params,
    step_write_provenance,
)
from hydromodpy.workflow.steps.prepare_solver.validate import (
    _store_sim_artifacts,
    collect_effective_config_snapshot,
    collect_run_facts,
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
    from hydromodpy.simulation.planning.planner import SimulationPlanner
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
    from hydromodpy.core.budget_terms import POLICY_ALL, kept_budget

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
    """Build the simulation plan and open the run it will execute.

    Composed from three sibling modules: :mod:`prepare` (writes inputs),
    :mod:`validate` (introspection) and :mod:`dispatch` (binding).

    Every write goes through a store this step opens and closes itself, so
    the handle is gone by the time the next step starts.
    """

    name = "prepare_solver"
    reads: ClassVar[tuple[str, ...]] = (
        "calibrated_by",
        "config_hash",
        "ctx",
        "lineage",
        "promotion",
        "run_dir",
        "run_overrides",
    )
    writes: ClassVar[tuple[str, ...]] = ("ctx",)
    config_sections: ClassVar[tuple[str, ...]] = (
        "flow",
        "transport",
        "solver",
        "modflownwt",
        "modflow6",
    )

    def depends_on(self) -> tuple[str, ...]:
        return ("setup_process",)

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("PrepareSolverStep requires 'ctx' in state.data")

        _resolve_plan_and_results(ctx)

        if run_is_persisted(ctx):
            bind_run_directory(
                ctx,
                run_dir=state.get("run_dir"),
                lineage=state.get("lineage"),
                calibrated_by=state.get("calibrated_by"),
                run_overrides=state.get("run_overrides"),
            )
            workspace = ctx.setup.workspace
            persistence = ctx.cfg.simulation.results.persistence
            facts = initial_facts(ctx, config_hash=state.get("config_hash"))
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
                step_write_provenance(ctx, store=store)
                step_persist_forcings(ctx, store=store)

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
            return _store_sim_artifacts(ctx, sim_id, store=store)

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
        store when the extraction already wrote it.
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
            with run_store(ctx) as store:
                _resolve_plan_and_results(ctx, store=store)

        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )


__all__ = (
    "PrepareSolverStep",
    "_register_tracked_input_files",
    "_store_sim_artifacts",
    "collect_effective_config_snapshot",
    "collect_run_facts",
    "step_persist_forcings",
    "step_persist_geographic",
    "step_persist_mesh",
    "step_persist_params",
    "step_open_run",
    "step_write_provenance",
)
