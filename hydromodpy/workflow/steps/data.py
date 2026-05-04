"""Data step - load external forcings, bind to runtime, expose ``LoadDataStep``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.time import resolve_simulation_time_window
from hydromodpy.physics.flow.structure_binders import (
    apply_etp_load_result_to_flow,
    apply_oceanic_to_flow,
    apply_recharge_load_result_to_flow,
)
from hydromodpy.simulation import ensure_flow
from hydromodpy.spatial.geographic.core.derived_features import (
    attach_reference_hydrographic_network,
)
from hydromodpy.spatial.geographic.structure_binders import apply_geology_to_domain
from hydromodpy.workflow.internals.state import GeographicState, LoadedState, PipelineState

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.data import DataLoadPlan

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lazy-import helpers (kept at module level for patchability in tests)
# ---------------------------------------------------------------------------


def _build_data_plan(*args, **kwargs):
    """Import planner lazily to keep launcher imports lightweight in tests."""
    from hydromodpy.data import DataPlanner

    return DataPlanner().build(*args, **kwargs)


def _build_data_runtime_loader(*args, **kwargs):
    """Import runtime loader lazily to avoid importing the full data stack at module import."""
    from hydromodpy.data import DataManagersRuntimeLoader

    return DataManagersRuntimeLoader(*args, **kwargs)


# ---------------------------------------------------------------------------
# Data plan logging
# ---------------------------------------------------------------------------


def log_data_plan(data_plan: DataLoadPlan) -> None:
    """Log concise planner diagnostics when inferred types are present."""
    if not data_plan.inferred_types:
        return
    logger.info(
        "[DataPlanner] inferred data types: %s",
        ", ".join(data_plan.inferred_types),
    )
    for type_name in data_plan.inferred_types:
        reasons = data_plan.reasons_for(type_name)
        if reasons:
            logger.info(
                "[DataPlanner] %s: %s",
                type_name,
                "; ".join(reasons),
            )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def run_data(
    config_path: str | Path,
    data_plan: DataLoadPlan,
    run_state: WorkflowContext,
) -> None:
    """Load the external forcings shared by all process runs.

    Runtime loading is delegated to ``DataManagersRuntimeLoader`` in the
    data_managers package. Structural bindings are then applied explicitly
    through domain/process binder modules.
    """
    loader = _build_data_runtime_loader(
        config_path=config_path,
        data_plan=data_plan,
    )
    loader.load_all(run_state)
    apply_structural_updates_from_data(run_state)


# ---------------------------------------------------------------------------
# Structural updates from loaded data
# ---------------------------------------------------------------------------


def apply_structural_updates_from_data(
    run_state: WorkflowContext,
) -> None:
    """Bind loaded data objects to runtime structures using explicit updaters."""
    setup_state = run_state.setup
    data_state = run_state.loaded_data
    apply_geology_to_domain(domain=setup_state.domain, geology=data_state.geology)
    ensure_flow(run_state)
    apply_oceanic_to_flow(flow=setup_state.flow, oceanic=data_state.oceanic)

    resolved_grid = getattr(setup_state, "time_grid", None)
    window = (
        resolved_grid.window
        if resolved_grid is not None
        else resolve_simulation_time_window(run_state.cfg)
    )
    apply_recharge_load_result_to_flow(
        flow=setup_state.flow,
        recharge_result=data_state.recharge,
        simulation_window=window,
    )
    apply_etp_load_result_to_flow(
        flow=setup_state.flow,
        etp_result=getattr(data_state, "etp", None),
        simulation_window=window,
    )
    if setup_state.geographic_features is not None:
        setup_state.geographic_features = attach_reference_hydrographic_network(
            setup_state.geographic_features,
            data_state.hydrography,
        )


# ---------------------------------------------------------------------------
# Step entry point (unified signature for workflow pipelines)
# ---------------------------------------------------------------------------


def step_data_loading(ctx: WorkflowContext) -> None:
    """Load forcings into ``ctx.loaded_data`` and bind them to runtime structures."""
    run_data(
        config_path=ctx.config_path,
        data_plan=ctx.data_plan,
        run_state=ctx,
    )


# ---------------------------------------------------------------------------
# Pipeline step
# ---------------------------------------------------------------------------


class LoadDataStep:
    """Ingest external + custom data via data managers."""

    name = "load_data"
    tin: ClassVar[type] = GeographicState
    tout: ClassVar[type] = LoadedState
    config_sections: ClassVar[tuple[str, ...]] = ("data",)

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("LoadDataStep requires 'ctx' in state.data")

        step_data_loading(ctx)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
