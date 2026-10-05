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

    from hydromodpy.core.field_routing import DownhillGraph

__all__ = ["Mesh", "MeshDescent", "RasterField", "Stack", "UGridStack"]


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
class MeshDescent:
    """The descent D of one run: where the water of each mesh face goes.

    Read-only arrays, one value per face. ``receiver`` is -1 at an outlet,
    ``surface`` the filled copy of the model top (NaN off the graph).
    ``constant_head`` flags the CHD cells, which keep a receiver so the
    accumulation crosses them; ``raised`` flags the cells D raised on its copy,
    where the routing departs from the model top. A run sealed before D was
    stored gets one rebuilt from its stored top (``rebuilt``): no channel pin,
    no constant-head seed, no lake.
    """

    receiver: np.ndarray
    surface: np.ndarray
    base_level: np.ndarray
    constant_head: np.ndarray
    raised: np.ndarray
    channel: np.ndarray
    pinned: np.ndarray
    graph: DownhillGraph
    """Receiver graph over ``receiver`` and ``surface``, ready to accumulate on."""
    adjacency: str
    """``"shared_nodes"`` (D8 on quads) or ``"shared_faces"``."""
    epsilon: float | None
    """Rise per fill step in metres, ``None`` when the store did not say."""
    report: dict[str, float]
    """Raise counts and maxima D logged at build time."""
    rebuilt: bool

    @property
    def diagonal_neighbors(self) -> bool:
        """Whether the graph pairs cells by shared nodes."""
        return self.adjacency == "shared_nodes"


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
