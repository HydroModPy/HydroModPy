"""Adapters that bind generic simulation runs to concrete solver APIs."""

from hydromodpy.simulation.adapters.base import SolverRunner
from hydromodpy.simulation.adapters.registry import get_solver_adapter, register_adapter

__all__ = [
    "SolverRunner",
    "get_solver_adapter",
    "register_adapter",
]
