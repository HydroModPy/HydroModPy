"""Backward-compatible workflow dispatch import path."""

from __future__ import annotations

from hydromodpy.project.dispatch.workflow import (
    DISPATCH,
    ProjectTestbedRunnerProvider,
    dispatch_workflow,
    run_calibration,
    run_comparison,
    run_overview,
    run_simulation,
    run_site_selection,
    run_testbed,
)

__all__ = [
    "DISPATCH",
    "ProjectTestbedRunnerProvider",
    "dispatch_workflow",
    "run_calibration",
    "run_comparison",
    "run_overview",
    "run_simulation",
    "run_site_selection",
    "run_testbed",
]
