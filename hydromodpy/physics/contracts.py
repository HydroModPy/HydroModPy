"""Shared process contracts used by HydroModPy internals.

This module provides the explicit import path for generic process-layer
building blocks such as ``ProcessSpatial`` and ``ProcessSpatialConfig``,
plus structural Protocols (``LoadResultProto``) used to type data-layer
inputs without importing them.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from hydromodpy.physics.base import (
    BoundaryCondition,
    InitialCondition,
    ProcessSpatial,
    ProcessSpatialConfig,
    SinkSource,
)


@runtime_checkable
class LoadResultProto(Protocol):
    """Structural view of ``data.contracts.LoadResult`` used by physics.

    Physics-layer binders consume data-manager outputs through this
    Protocol so the physics package never imports the data package.
    """

    points: list
    fields: list

    @property
    def has_points(self) -> bool: ...

    @property
    def has_fields(self) -> bool: ...


__all__ = [
    "BoundaryCondition",
    "InitialCondition",
    "LoadResultProto",
    "ProcessSpatial",
    "ProcessSpatialConfig",
    "SinkSource",
]
