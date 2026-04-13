"""Data phase — re-exports from ``hydromodpy.workflow.steps.data_loading``.

This module is kept for backward compatibility.  All implementation has
moved to :mod:`hydromodpy.workflow.steps.data_loading`.
"""

from hydromodpy.workflow.steps.data_loading import (  # noqa: F401
    _build_data_plan,
    _build_data_runtime_loader,
    log_data_plan,
    run_data,
    apply_structural_updates_from_data,
    step_data_loading,
)
