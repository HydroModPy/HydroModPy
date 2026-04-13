"""Transient hillslope overflow case with configurable PETSc surface formulations."""

from .animation import (
    OverflowAnimationOptions,
    build_hillslope_overflow_animation,
)
from .comparison import (
    HillslopeOverflowScenario,
    run_hillslope_overflow_scenario,
)
from .diagnostics import (
    SolverOverflowDiagnostics,
    build_hillslope_overflow_diagnostics,
)
from .runtime_boussinesq import (
    DEFAULT_SOLVER,
    SolverVariant,
    resolve_solver_variant,
    run_boussinesq_hillslope_overflow_case,
)

__all__ = [
    "DEFAULT_SOLVER",
    "HillslopeOverflowScenario",
    "OverflowAnimationOptions",
    "SolverOverflowDiagnostics",
    "SolverVariant",
    "build_hillslope_overflow_diagnostics",
    "build_hillslope_overflow_animation",
    "resolve_solver_variant",
    "run_boussinesq_hillslope_overflow_case",
    "run_hillslope_overflow_scenario",
]
