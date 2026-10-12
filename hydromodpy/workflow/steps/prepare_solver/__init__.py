"""Prepare-solver step decomposed into 3 concerns.

The original 941-LOC monolith now lives in three sibling modules:

- :mod:`prepare` - persistence helpers (params, mesh, geographic,
  provenance, forcings).
- :mod:`validate` - pure validators and artefact discovery helpers
  (``_primary_solver_for_simulation``, ``collect_registration_kwargs``,
  ``_store_sim_artifacts``).
- :mod:`dispatch` - registration of the run and of what it was built from
  (``step_register_run``).

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
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.run_catalog import run_catalog, run_is_catalogued
from hydromodpy.workflow.steps.prepare_solver.dispatch import (
    _register_tracked_input_files,
    step_register_run,
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
    collect_registration_kwargs,
)

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext

logger = get_logger(__name__)


def _resolve_plan_and_results(ctx, *, skip_display: bool, store=None) -> None:
    """Populate the simulation plan and the per-cell budget the run keeps.

    The plan is a deterministic derivation of the config. The budget policy
    is decided once, at planning: a resumed run whose store already says what
    its extraction kept (the ``budget/`` attributes) takes it from there, so
    the display flag of the resuming invocation cannot change it. ``store`` is
    the open catalog of a resume; a fresh run passes none.
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
        display_active=not skip_display,
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
    """Build the simulation plan and register the run it will execute.

    Composed from three sibling modules: :mod:`prepare` (writes inputs),
    :mod:`validate` (introspection) and :mod:`dispatch` (registration).

    Every write goes through a catalog this step opens and closes itself, so
    the handle is gone by the time the next step starts.
    """

    name = "prepare_solver"
    reads: ClassVar[tuple[str, ...]] = (
        "ctx",
        "skip_display",
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

        _resolve_plan_and_results(ctx, skip_display=bool(state.get("skip_display")))

        if run_is_catalogued(ctx):
            with run_catalog(ctx) as store:
                step_register_run(ctx, store=store, run_overrides=state.get("run_overrides"))
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
        """Recover the identity of the run a previous ``run`` call registered.

        The plan is a pure function of the config, so it is recomputed here.
        The per-cell budget policy is read back from the store when the
        extraction already wrote it, and decided again otherwise: a run
        resumed after its extraction keeps the policy it was extracted under.
        """
        from hydromodpy.results.catalog import (
            AmbiguousReferenceError,
            SimulationNotFoundError,
        )

        ctx = prior_state.get("ctx")
        if ctx is None:
            raise ConfigError("PrepareSolverStep.rebuild_state requires 'ctx' in state.data")

        ws = getattr(getattr(ctx, "setup", None), "workspace", None)
        if ws is None:
            raise ConfigError(
                "PrepareSolverStep.rebuild_state requires a resolved workspace on the context"
            )

        skip_display = bool(prior_state.get("skip_display"))
        if not run_is_catalogued(ctx):
            _resolve_plan_and_results(ctx, skip_display=skip_display)
        else:
            with run_catalog(ctx) as store:
                if getattr(ctx, "sim_id", None) is None:
                    # Resolve the resumed run by its NAME (the identity column), not by
                    # "latest sim in project", so a resume after a later run was
                    # registered attaches to the right simulation, not the newest one.
                    # The index is per project, so the directory name is not part of
                    # the lookup: renaming or copying a project must not break resume.
                    # ``find`` and not ``resolve``: the resume knows the name it wrote
                    # and wants that row or nothing. ``resolve`` also accepts a run id
                    # prefix and falls back to the newest version of a name stem, and
                    # a resume that lands on ``foo.v3`` because ``foo`` no longer
                    # exists writes a journal into the wrong simulation.
                    sim_ids = store.find(name=run_id).sim_ids
                    if not sim_ids:
                        raise SimulationNotFoundError(
                            f"resume: no simulation named {run_id!r} in the project index at "
                            f"{ws.project_root}; cannot rebuild the run state."
                        )
                    if len(sim_ids) > 1:
                        raise AmbiguousReferenceError(run_id, [(sid, run_id) for sid in sim_ids])
                    ctx.sim_id = sim_ids[0]
                _resolve_plan_and_results(ctx, skip_display=skip_display, store=store)

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
    "collect_registration_kwargs",
    "step_persist_forcings",
    "step_persist_geographic",
    "step_persist_mesh",
    "step_persist_params",
    "step_register_run",
    "step_write_provenance",
)
