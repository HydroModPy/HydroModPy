"""Shared solver contracts used by HydroModPy internals.

This module is the explicit import path for generic solver abstractions such
as ``Solver`` and ``SolverConfig``. Concrete solver implementations remain
available from their dedicated subpackages (for example
``hydromodpy.solver.modflow6`` and ``hydromodpy.solver.boussinesq``).
"""

from hydromodpy.solver.base import Solver, SolverConfig, SolverEngine

__all__ = ["Solver", "SolverConfig", "SolverEngine"]
