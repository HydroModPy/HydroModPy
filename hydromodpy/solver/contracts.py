"""Shared solver contracts used by HydroModPy internals.

Public import path for the structural :class:`SolverAdapter` Protocol that
every adapter must satisfy, the :class:`RunResult` payload dataclass, and the
solver-adapter ``registry`` module. Concrete numerical model classes such as
``Modflow6`` or ``Boussinesq`` keep using :class:`Solver` from
:mod:`hydromodpy.solver.base.solver` as an internal lifecycle convention.
"""

from hydromodpy.solver.base import (
    RunResult,
    Solver,
    SolverAdapter,
    SolverConfig,
    SolverEngine,
    registry,
)

__all__ = [
    "RunResult",
    "Solver",
    "SolverAdapter",
    "SolverConfig",
    "SolverEngine",
    "registry",
]
