"""Generic solver base classes shared by concrete solver backends."""

from hydromodpy.solver.base import registry
from hydromodpy.solver.base.protocol import RunResult, SolverAdapter
from hydromodpy.solver.base.protocols import DomainLike, FlowModelLike, TransportLike
from hydromodpy.solver.base.solver_config import SolverConfig

__all__ = [
    "DomainLike",
    "FlowModelLike",
    "RunResult",
    "SolverAdapter",
    "SolverConfig",
    "TransportLike",
    "registry",
]
