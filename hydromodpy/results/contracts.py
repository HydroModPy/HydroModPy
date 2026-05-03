"""Strong-typed return contracts for ``Run`` field/raster/mesh accessors.

These dataclasses replace the legacy ``dict`` and ``tuple`` payloads
returned by :class:`~hydromodpy.results.run.Run`. Frozen + slotted: cheap
to allocate, immutable for callers, attribute access only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from dask.array import Array as DaskArray

__all__ = ["Mesh", "RasterField", "Stack", "UGridStack"]


@dataclass(frozen=True, slots=True)
class Mesh:
    """UGRID mesh payload for a single simulation."""

    vertices: np.ndarray
    face_node_connectivity: np.ndarray
    z_interfaces: np.ndarray


@dataclass(frozen=True, slots=True)
class RasterField:
    """Single-band raster with georeferencing metadata."""

    data: np.ndarray
    transform: tuple[float, ...]
    crs: str
    nodata: float
    shape: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Stack:
    """Time stack of regular-in-plan rasters as ``(n_t, nrow, ncol)``."""

    data: np.ndarray | DaskArray
    variable: str


@dataclass(frozen=True, slots=True)
class UGridStack:
    """Time stack of UGRID per-cell field values as ``(n_t, n_cells)``."""

    data: np.ndarray
    variable: str
    mesh: Mesh
