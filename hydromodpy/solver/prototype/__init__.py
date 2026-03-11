"""Generic solver prototypes shared by concrete solver backends."""

from hydromodpy.solver.prototype.solver import Solver
from hydromodpy.solver.prototype.solver_config import SolverConfig
from hydromodpy.solver.prototype.solver_engine import SolverEngine

__all__ = [
    "Solver",
    "SolverConfig",
    "SolverEngine",
]

