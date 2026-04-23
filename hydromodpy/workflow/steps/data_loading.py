"""Data-loading step - load external forcings and apply structural bindings.

This module contains the functions that load external forcings and bind the
loaded data objects to runtime structures.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.time import resolve_simulation_time_window
from hydromodpy.physics.flow.structure_binders import (
    apply_oceanic_to_flow,
    apply_recharge_load_result_to_flow,
)
from hydromodpy.simulation import ensure_flow
from hydromodpy.spatial.geographic.structure_binders import apply_geology_to_domain

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.data import DataLoadPlan

logger = logging.getLogger(__name__)


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
