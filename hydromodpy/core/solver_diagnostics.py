"""Stable names for persisted solver diagnostic artifacts.

These constants describe files written to run folders or exported
``solver_diagnostics`` directories. They live in ``core`` so result-analysis
code can discover persisted artifacts without importing concrete solver
runtime modules.
"""

from __future__ import annotations

VI_OBSTACLE_RUNTIME_SUMMARY_JSON = "vi_obstacle_runtime_summary.json"
VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV = "vi_obstacle_period_diagnostics.csv"
VI_OBSTACLE_SUBSTEP_DIAGNOSTICS_CSV = "vi_obstacle_substep_diagnostics.csv"

TS_VI_OBSTACLE_RUNTIME_SUMMARY_JSON = "ts_vi_obstacle_runtime_summary.json"
TS_VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV = "ts_vi_obstacle_period_diagnostics.csv"
TS_VI_OBSTACLE_STEP_DIAGNOSTICS_CSV = "ts_vi_obstacle_step_diagnostics.csv"

STATIONARY_FAILURE_SUMMARY_JSON = "stationary_failure_summary.json"
STATIONARY_FAILURE_CELLS_TOP_RESIDUAL_CSV = "stationary_failure_cells_top_residual.csv"
STATIONARY_FAILURE_ACTIVE_SET_SUMMARY_CSV = "stationary_failure_active_set_summary.csv"
STATIONARY_FAILURE_FIELD_STATS_JSON = "stationary_failure_field_stats.json"

__all__ = [
    "STATIONARY_FAILURE_ACTIVE_SET_SUMMARY_CSV",
    "STATIONARY_FAILURE_CELLS_TOP_RESIDUAL_CSV",
    "STATIONARY_FAILURE_FIELD_STATS_JSON",
    "STATIONARY_FAILURE_SUMMARY_JSON",
    "TS_VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV",
    "TS_VI_OBSTACLE_RUNTIME_SUMMARY_JSON",
    "TS_VI_OBSTACLE_STEP_DIAGNOSTICS_CSV",
    "VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV",
    "VI_OBSTACLE_RUNTIME_SUMMARY_JSON",
    "VI_OBSTACLE_SUBSTEP_DIAGNOSTICS_CSV",
]
