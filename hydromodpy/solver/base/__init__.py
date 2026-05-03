"""Generic solver base classes shared by concrete solver backends."""

from hydromodpy.solver.base import registry
from hydromodpy.solver.base.protocol import RunResult, SolverAdapter
from hydromodpy.solver.base.solver import Solver
from hydromodpy.solver.base.solver_config import SolverConfig

__all__ = [
    "RunResult",
    "Solver",
    "SolverAdapter",
    "SolverConfig",
    "registry",
]
