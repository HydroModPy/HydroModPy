"""Structural protocols for solver init signatures.

These ``typing.Protocol`` classes capture the minimal duck-typed contract
historically expressed by ``object`` annotations on solver constructors.
They are structural (PEP 544) so no concrete class has to inherit from
them: any object exposing the listed attributes satisfies the protocol.

Kept attribute typing intentionally loose (``Any``) to avoid pulling the
flow/transport/domain runtime modules into the solver kernel.
"""

from __future__ import annotations

from typing import Any, Protocol


class FlowModelLike(Protocol):
    """Minimal contract a flow model must satisfy to drive a transport solver."""

    exe: str
    sim: Any
    gwf: Any
    nlay: int
    ncpl: int
    nper: int
    solver_mesh: Any

    @property
    def sy(self) -> Any: ...


class TransportLike(Protocol):
    """Container exposing per-backend transport parameter blocks."""

    modpath: Any
    mt3dms: Any
    modflow6gwt: Any
    modflow6prt: Any


class DomainLike(Protocol):
    """Catchment domain object passed through solver constructors."""

    config: Any
    surface_topo: Any
    substratum: Any
    zones: Any


__all__ = ["DomainLike", "FlowModelLike", "TransportLike"]
