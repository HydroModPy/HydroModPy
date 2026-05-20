"""Shared solver contracts used by HydroModPy internals.

Public import path for the structural :class:`SolverAdapter` Protocol that
every adapter must satisfy, the :class:`RunResult` payload dataclass, and the
solver-adapter ``registry`` module. Concrete numerical model classes such as
``Modflow6`` or ``Boussinesq`` implement the lifecycle methods
(``pre_processing``, ``processing``, ``post_processing``) directly without a
shared base class: structural conformance through the ``SolverAdapter``
Protocol is the only contract.
"""

from hydromodpy.solver.base import (
    RunResult,
    SolverAdapter,
    SolverConfig,
    registry,
)

__all__ = [
    "RunResult",
    "SolverAdapter",
    "SolverConfig",
    "registry",
]
