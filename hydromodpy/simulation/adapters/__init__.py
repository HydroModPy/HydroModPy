"""Adapters that bind generic simulation runs to concrete solver APIs."""

from hydromodpy.simulation.adapters.base import SolverAdapter
from hydromodpy.simulation.adapters.registry import get_solver_adapter, register_adapter

__all__ = [
    "SolverAdapter",
    "get_solver_adapter",
    "register_adapter",
]
