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

__all__ = [
    "TS_VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV",
    "TS_VI_OBSTACLE_RUNTIME_SUMMARY_JSON",
    "TS_VI_OBSTACLE_STEP_DIAGNOSTICS_CSV",
    "VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV",
    "VI_OBSTACLE_RUNTIME_SUMMARY_JSON",
    "VI_OBSTACLE_SUBSTEP_DIAGNOSTICS_CSV",
]
