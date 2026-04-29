"""Step 6 - prepare the solver store and the simulation plan.

Builds the :class:`SimulationPlan` (if not already present in the
context) and opens the ``SimulationCatalog`` store so subsequent steps
can write Zarr fields and DuckDB rows.

Inputs
------
``ctx`` : WorkflowContext

Outputs
-------
``ctx`` : same context with ``execution.simulation_plan`` and ``store``
attached.
"""

from __future__ import annotations

from typing import ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.internals.state import OpenStoreState, PipelineState, SetupState


class PrepareSolverStep:
    """Build the simulation plan + open the store."""

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

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.simulation.planning.planner import SimulationPlanner
        from hydromodpy.workflow.steps.result_ingestion import (
            step_persist_forcings,
            step_write_provenance,
        )
        from hydromodpy.workflow.steps.store_lifecycle import step_open_store

        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("PrepareSolverStep requires 'ctx' in state.data")

        if ctx.execution.simulation_plan is None:
            sim_cfg = getattr(ctx.cfg, "simulation", None)
            if sim_cfg is not None:
                ctx.execution.simulation_plan = SimulationPlanner().build(sim_cfg)

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
