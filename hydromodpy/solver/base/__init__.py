"""Generic solver base classes shared by concrete solver backends."""

from hydromodpy.solver.base import registry
from hydromodpy.solver.base.protocol import RunResult, SolverRunner
from hydromodpy.solver.base.solver import Solver
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.base.solver_engine import SolverEngine

__all__ = [
    "RunResult",
    "Solver",
    "SolverRunner",
    "SolverConfig",
    "SolverEngine",
    "registry",
]
