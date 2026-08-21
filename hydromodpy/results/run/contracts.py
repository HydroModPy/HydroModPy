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
    topography: np.ndarray | None = None
    """Per-face model top (conditioned), when persisted in the mesh group."""
    topography_reference: np.ndarray | None = None
    """Per-face model top BEFORE conditioning, when persisted (for the impact map)."""
    crs: str | None = None
    """Projected CRS the vertices are expressed in (``crs_proj``), ``None`` when
    the run pre-dates geographic ingestion. Overlaying a vector layer on this mesh
    needs it: bare coordinates say nothing about the frame they belong to."""


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
