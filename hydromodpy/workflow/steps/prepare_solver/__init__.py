"""Prepare-solver step decomposed into 3 concerns.

The original 941-LOC monolith now lives in three sibling modules:

- :mod:`prepare` - persistence helpers (params, mesh, geographic,
  provenance, forcings).
- :mod:`validate` - pure validators and artefact discovery helpers
  (``_primary_solver_for_simulation``, ``collect_registration_kwargs``,
  ``_store_sim_artifacts``).
- :mod:`dispatch` - registration and store opening
  (``step_register_simulation``, ``step_open_store``).

The :class:`PrepareSolverStep` class itself sits in this ``__init__`` so
its public import path is preserved
(``from hydromodpy.workflow.steps.prepare_solver import PrepareSolverStep``).
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import OpenStoreState, PipelineState, SetupState
from hydromodpy.workflow.steps.prepare_solver.dispatch import (
    _register_tracked_input_files,
    step_open_store,
    step_register_simulation,
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

logger = get_logger(__name__)


class PrepareSolverStep:
    """Build the simulation plan + open the store.

    Composed from three sibling modules: :mod:`prepare` (writes inputs),
    :mod:`validate` (introspection) and :mod:`dispatch` (catalog setup).
    """

    name = "prepare_solver"
    tin: ClassVar[type] = SetupState
    tout: ClassVar[type] = OpenStoreState
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
        from hydromodpy.simulation.planning.planner import SimulationPlanner
        from hydromodpy.workflow.steps.planning import step_configure_results

        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("PrepareSolverStep requires 'ctx' in state.data")

        if ctx.execution.simulation_plan is None:
            sim_cfg = getattr(ctx.cfg, "simulation", None)
            if sim_cfg is not None:
                ctx.execution.simulation_plan = SimulationPlanner().build(sim_cfg)

        if ctx.execution.simulation_plan is not None:
            ctx.effective_results_config = step_configure_results(
                ctx.cfg.simulation.results,
                ctx.execution.simulation_plan,
            )

        if not ctx.execution.lightweight:
            step_open_store(ctx)

            if ctx.store is not None:
                step_write_provenance(ctx)
                step_persist_forcings(ctx)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )

    def artifacts(self, state: PipelineState) -> tuple[str, ...]:
        """Return workspace-relative paths persisted by this step."""
        ctx = state.get("ctx")
        if ctx is None or getattr(ctx, "store", None) is None:
            return ()
        sim_id = getattr(ctx, "sim_id", None)
        if not sim_id:
            return ()
        return _store_sim_artifacts(ctx, sim_id)

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        """Reopen the simulation store written by a previous ``run`` call."""
        from hydromodpy.results.catalog import Catalog

        ctx = prior_state.get("ctx")
        if ctx is None:
            raise ConfigError("PrepareSolverStep.rebuild_state requires 'ctx' in state.data")

        ws = getattr(getattr(ctx, "setup", None), "workspace", None)
        if ws is None:
            raise ConfigError(
                "PrepareSolverStep.rebuild_state requires a resolved workspace on the context"
            )

        sim_id = getattr(ctx, "sim_id", None)
        results_cfg = getattr(ctx, "effective_results_config", None) or ctx.cfg.simulation.results
        if ctx.store is None and results_cfg.persistence.save_catalog:
            ctx.store = Catalog.from_workspace(
                ws,
                persistence=results_cfg.persistence,
            )
            if sim_id is None:
                row = ctx.store.connection.execute(
                    "SELECT sim_id FROM simulations WHERE project = ? ORDER BY created_at DESC LIMIT 1",
                    [ws.project_root.name],
                ).fetchone()
                if row is not None:
                    ctx.sim_id = str(row[0])

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
    "step_open_store",
    "step_persist_forcings",
    "step_persist_geographic",
    "step_persist_mesh",
    "step_persist_params",
    "step_register_simulation",
    "step_write_provenance",
)
