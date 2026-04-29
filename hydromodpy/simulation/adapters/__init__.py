"""Adapters that bind generic simulation runs to concrete solver APIs.

The single :class:`SolverAdapter` Protocol consumed by the simulation
runner lives in :mod:`hydromodpy.solver.base.protocol`. Adapter classes
are stored in the canonical registry at
:mod:`hydromodpy.solver.base.registry` — import ``get_solver_adapter``
from there.
"""

from hydromodpy.solver.base.protocol import SolverAdapter

__all__ = ["SolverAdapter"]
