"""Adapters that bind generic simulation runs to concrete solver APIs.

The ``SolverRunner`` protocol exposed here is the single-method contract
expected by :class:`hydromodpy.simulation.execution.runner.SimulationRunner`.
Adapter classes are stored in the canonical registry at
:mod:`hydromodpy.solver.base.registry` — import
``get_solver_adapter`` from there rather than from this package.
"""

from hydromodpy.simulation.adapters.base import SolverRunner

__all__ = ["SolverRunner"]
