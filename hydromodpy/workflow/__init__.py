"""Composable workflow layer for HydroModPy simulation pipelines.

This package extracts the business logic from launchers into reusable
steps and pipelines, so that a single logic path serves TOML-driven,
programmatic (Project), and calibration usage modes.

Public API
----------
WorkflowContext
    Extended run state with result-store lifecycle support.
"""

from hydromodpy.workflow.context import WorkflowContext

__all__ = ["WorkflowContext"]
