"""Strong-typed return contracts for ``Run`` field/raster/mesh accessors.

These dataclasses replace the legacy ``dict`` and ``tuple`` payloads
returned by :class:`~hydromodpy.results.run.Run`. Frozen + slotted: cheap
to allocate, immutable for callers, attribute access only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import numpy as np

from hydromodpy.spatial.mesh.model.geometry import cell_areas, padded_rows

if TYPE_CHECKING:
    from dask.array import Array as DaskArray

    from hydromodpy.spatial.drainage.graph import DownhillGraph

__all__ = [
    "Mesh",
    "MeshDescent",
    "MeshStoreIdentity",
    "RasterField",
    "Stack",
    "UGridStack",
    "cell_centers",
    "polygon_areas",
]


def cell_centers(
    vertices: np.ndarray,
    faces: np.ndarray,
    face_x: np.ndarray | None = None,
    face_y: np.ndarray | None = None,
) -> np.ndarray:
    """Return the ``(n_faces, 2)`` centers the field arrays of a run are indexed by.

    The stored ``face_x`` / ``face_y`` when the mesh group has them, else the
    mean of the corners of each face. ``faces`` is the padded UGRID
    connectivity: corner slots below zero are padding. The one rule every
    reader that places a field value in space goes through.
    """
    if face_x is not None and face_y is not None:
        return np.column_stack((np.asarray(face_x, dtype=float), np.asarray(face_y, dtype=float)))
    xy = np.asarray(vertices, dtype=float)[:, :2]
    rows = np.asarray(faces)
    valid = rows >= 0
    safe = np.where(valid, rows, 0)
    count = valid.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        cx = np.where(valid, xy[safe, 0], 0.0).sum(axis=1) / count
        cy = np.where(valid, xy[safe, 1], 0.0).sum(axis=1) / count
    return np.column_stack((cx, cy))


def polygon_areas(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Return the shoelace area of each face, ``NaN`` for a face of fewer than 3 corners.

    The shoelace sum is taken relative to the first corner, which keeps the
    precision of coordinates expressed in a projected CRS (6e6 m northings).
    """
    rows = np.asarray(faces)
    if rows.dtype.kind == "f":
        rows = padded_rows(rows, n_nodes=len(vertices))
    return np.where((rows >= 0).sum(axis=1) >= 3, cell_areas(vertices, rows), np.nan)


@dataclass(frozen=True, slots=True)
class MeshStoreIdentity:
    """Who built the mesh of a run, as the ``mesh/`` group of its store says."""

    engine: str
    engine_version: str | None = None
    request_hash: str | None = None
    center_kind: str | None = None
    seed: int | None = None


@dataclass(frozen=True, slots=True)
class Mesh:
    """UGRID mesh payload for a single simulation."""

    vertices: np.ndarray
    face_node_connectivity: np.ndarray
    z_interfaces: np.ndarray
    """Interfaces of every cell, ``(n_layers + 1, n_faces)``: row 0 is the model
    top, row ``k + 1`` the bottom of layer ``k``."""
    topography: np.ndarray | None = None
    """Per-face model top, when persisted in the mesh group."""
    crs: str | None = None
    """Projected CRS the vertices are expressed in (``crs_proj``), ``None`` when
    the run pre-dates geographic ingestion. Overlaying a vector layer on this mesh
    needs it: bare coordinates say nothing about the frame they belong to."""
    structured_shape: tuple[int, int] | None = None
    """``(nrow, ncol)`` when the run was solved on a regular grid, rows north
    first; ``None`` for any other mesh."""
    face_x: np.ndarray | None = None
    face_y: np.ndarray | None = None
    """Per-face centers, when the mesh group stores them."""
    identity: MeshStoreIdentity | None = None
    """Engine, version, request hash and center rule of the stored mesh."""
    crs_source: Literal["mesh", "catalog"] | None = None
    """Where ``crs`` was read: the ``mesh/`` group, else the catalog, ``None`` when
    neither says."""

    def cell_centers(self) -> np.ndarray:
        """Return the ``(n_faces, 2)`` centers the field arrays are indexed by.

        The stored ``face_x`` / ``face_y`` when the mesh group has them, else
        the mean of each face's corners. Every reader that needs to place a
        field value in space (bounding box, point lookup) goes through here.
        """
        return cell_centers(self.vertices, self.face_node_connectivity, self.face_x, self.face_y)

    def cell_areas(self) -> np.ndarray:
        """Return the ``(n_faces,)`` plan area of each face in square meters."""
        return polygon_areas(self.vertices, self.face_node_connectivity)

    def cells_in_bbox(self, bbox: tuple[float, float, float, float]) -> np.ndarray:
        """Return the boolean mask of faces whose center lies in ``bbox``.

        ``bbox`` is ``(xmin, ymin, xmax, ymax)`` in the CRS of the vertices,
        edges included.
        """
        xmin, ymin, xmax, ymax = (float(v) for v in bbox)
        if not (xmin < xmax and ymin < ymax):
            raise ValueError(f"bbox must satisfy xmin<xmax and ymin<ymax; got {bbox!r}")
        centers = self.cell_centers()
        return (
            (centers[:, 0] >= xmin)
            & (centers[:, 0] <= xmax)
            & (centers[:, 1] >= ymin)
            & (centers[:, 1] <= ymax)
        )


@dataclass(frozen=True, slots=True)
class MeshDescent:
    """The descent D of one run: where the water of each mesh face goes.

    Read-only arrays, one value per face. ``receiver`` is -1 at an outlet,
    ``surface`` the filled copy of the model top (NaN off the graph).
    ``constant_head`` flags the CHD cells, which keep a receiver so the
    accumulation crosses them; ``raised`` flags the cells D raised on its copy,
    where the routing departs from the model top. A run sealed before D was
    stored gets one rebuilt from its stored top (``rebuilt``): no channel pin,
    no constant-head seed, no lake. ``basin`` is the basin of D at the catchment
    outlet, one flag per face, outlet included; it is ``None`` for a rebuilt D
    and for a run sealed before the basin was stored.
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
    """Rise per fill step in meters, ``None`` when the store did not say."""
    report: dict[str, float]
    """Raise counts and maxima D logged at build time."""
    rebuilt: bool
    dam_foot: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    """Cell ids below the dams, where the stream under a lake starts. Empty for a
    run with no lake, a run sealed before they were stored, or a rebuilt D."""
    basin: np.ndarray | None = None
    """Basin of D at the catchment outlet, a read-only bool per face, ``None`` when not stored."""
    basin_attrs: dict[str, object] = field(default_factory=dict)
    """Attributes of the stored basin: ``descent_outlet`` (the outlet cell), ``basin_rule`` (how
    the outlet was found), ``basin_area_m2``, ``basin_seeded_at_outlet`` and ``basin_version``.
    Empty when no basin is stored."""

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
