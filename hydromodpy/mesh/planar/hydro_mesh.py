"""Unified mesh data container for HydroModPy.

``HydroMesh`` is a thin, frozen data object that every mesh-producing or
mesh-consuming module can accept or return.  It follows the meshio data model
(vertices + connectivity + per-cell / per-point data dictionaries) so that
round-trips through meshio are lossless, while remaining solver-agnostic.

Whether the mesh is a regular structured grid or an irregular triangulation
is expressed by the *cell types* stored in ``cell_blocks`` and the optional
``structured_shape`` hint.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from hydromodpy.mesh.planar.cell_types import CellType


@dataclass(frozen=True)
class CellBlock:
    """One homogeneous block of cells sharing the same geometry type.

    A mesh may contain several blocks (e.g. triangles + quads in a hybrid
    mesh, or wedges across multiple physical groups).  Most HydroModPy meshes
    carry a single block.

    ``connectivity`` is one ``(n_cells, k)`` int table, one row of node indices
    per cell. A ``POLYGON`` block has as many columns as its largest cell: the
    nodes of a cell fill its row from the left and the free slots hold ``-1``.
    One node array per cell is accepted for a polygon block and padded so.
    """

    cell_type: CellType
    connectivity: np.ndarray

    def __post_init__(self) -> None:
        """Normalize and validate the connectivity table."""
        ct = self.cell_type
        if not isinstance(ct, CellType):
            object.__setattr__(self, "cell_type", CellType.from_string(str(ct)))
            ct = self.cell_type
        if ct.is_ragged:
            object.__setattr__(self, "connectivity", _polygon_rows(self.connectivity, ct))
            return
        conn = np.asarray(self.connectivity, dtype=int)
        if conn.ndim != 2 or conn.shape[1] != ct.nodes_per_cell:
            raise ValueError(
                f"{ct.value} connectivity must have shape (n_cells, {ct.nodes_per_cell}), "
                f"got {conn.shape}"
            )
        object.__setattr__(self, "connectivity", conn.copy())

    @property
    def n_cells(self) -> int:
        """Number of cells in this block."""
        return int(self.connectivity.shape[0])


def _polygon_rows(
    connectivity: np.ndarray | Sequence[np.ndarray], cell_type: CellType
) -> np.ndarray:
    """Return polygon cells as one int table padded with ``-1`` on the right.

    A per-cell node array holds node ids only, so a negative entry in it is refused.
    """
    if isinstance(connectivity, np.ndarray) and connectivity.ndim == 2:
        table = np.asarray(connectivity, dtype=int).copy()
    else:
        cells = [np.asarray(c, dtype=int).ravel() for c in connectivity]
        if any(c.size and int(c.min()) < 0 for c in cells):
            raise ValueError(
                f"connectivity in {cell_type.value} block references node indices outside vertices"
            )
        lengths = np.fromiter((c.size for c in cells), dtype=int, count=len(cells))
        table = np.full((len(cells), int(lengths.max(initial=0))), -1, dtype=int)
        if cells:
            owner = np.repeat(np.arange(len(cells)), lengths)
            starts = np.cumsum(lengths) - lengths
            table[owner, np.arange(owner.size) - starts[owner]] = np.concatenate(cells)
    used = table >= 0
    counts = used.sum(axis=1)
    if np.any(counts < 3):
        raise ValueError(f"{cell_type.value} cell needs >= 3 node indices, got {int(counts.min())}")
    if np.any(table[~used] != -1) or np.any(used[:, 1:] & ~used[:, :-1]):
        raise ValueError(f"{cell_type.value} rows hold their nodes first, then -1 padding")
    return table


@dataclass(frozen=True)
class HydroMesh:
    """Unified mesh pivot for structured and unstructured grids.

    Parameters
    ----------
    vertices : ndarray, shape (n_nodes, 2) or (n_nodes, 3)
        Node coordinates.  2-column for planar meshes, 3-column for 3D.
    cell_blocks : tuple of CellBlock
        One or more homogeneous connectivity blocks.
    cell_data : dict[str, ndarray]
        Per-cell scalar fields.  Each value has shape ``(total_n_cells,)``.
    point_data : dict[str, ndarray]
        Per-point scalar fields.  Each value has shape ``(n_nodes,)``.
    structured_shape : tuple of int, optional
        ``(nrow, ncol)`` for 2D structured grids, ``(nlay, nrow, ncol)`` for
        3D.  When set, signals that the vertices follow a regular grid layout
        and enables optimized adapters (e.g. flopy DIS).
    """

    vertices: np.ndarray
    cell_blocks: tuple[CellBlock, ...]
    cell_data: dict[str, np.ndarray] = field(default_factory=dict)
    point_data: dict[str, np.ndarray] = field(default_factory=dict)
    structured_shape: tuple[int, ...] | None = None
    """``(nrow, ncol)`` or ``(nlay, nrow, ncol)`` of a structured grid, else ``None``."""

    def __post_init__(self) -> None:
        """Validate node coordinates and connectivity consistency."""
        verts = np.asarray(self.vertices, dtype=float)
        if verts.ndim != 2 or verts.shape[1] not in (2, 3):
            raise ValueError(f"vertices must have shape (n_nodes, 2|3), got {verts.shape}")
        object.__setattr__(self, "vertices", verts.copy())

        if not self.cell_blocks:
            raise ValueError("cell_blocks must contain at least one block")

        n_nodes = verts.shape[0]
        for block in self.cell_blocks:
            conn = block.connectivity
            low = -1 if block.cell_type.is_ragged else 0
            if np.any(conn < low) or np.any(conn >= n_nodes):
                raise ValueError(
                    f"connectivity in {block.cell_type.value} block references "
                    "node indices outside vertices"
                )

    # -- Convenience properties -----------------------------------------------

    @property
    def ndim(self) -> int:
        """Spatial dimension (2 or 3)."""
        return int(self.vertices.shape[1])

    @property
    def n_nodes(self) -> int:
        """Number of mesh nodes (cell corners)."""
        return int(self.vertices.shape[0])

    @property
    def n_cells(self) -> int:
        """Number of cells, summed over every cell block."""
        return sum(b.n_cells for b in self.cell_blocks)

    @property
    def is_structured(self) -> bool:
        """True for a regular grid, the one ``structured_shape`` describes."""
        return self.structured_shape is not None

    @property
    def cell_types(self) -> tuple[CellType, ...]:
        """Cell type of each cell block, in block order.

        A mesh of one block, the usual case, gives a one-element tuple.
        """
        return tuple(b.cell_type for b in self.cell_blocks)

    @property
    def single_cell_type(self) -> CellType:
        """Return the unique cell type, or raise if mixed."""
        types = set(self.cell_types)
        if len(types) != 1:
            raise ValueError(f"Mesh has mixed cell types: {[t.value for t in types]}")
        return next(iter(types))

    @property
    def flat_connectivity(self) -> np.ndarray:
        """Connectivity across all blocks as one ``(n_cells, k)`` int table.

        A single block is returned as it is. Blocks of different widths are
        padded with ``-1`` to the widest one, like the rows of a polygon block.
        """
        if len(self.cell_blocks) == 1:
            return self.cell_blocks[0].connectivity
        width = max(b.connectivity.shape[1] for b in self.cell_blocks)
        return np.vstack(
            [
                np.pad(
                    b.connectivity,
                    ((0, 0), (0, width - b.connectivity.shape[1])),
                    constant_values=-1,
                )
                for b in self.cell_blocks
            ]
        ).astype(int, copy=False)

    def bounds(self) -> tuple[float, ...]:
        """Return ``(xmin, ymin, [zmin,] xmax, ymax, [zmax])``."""
        mins = tuple(float(np.nanmin(self.vertices[:, i])) for i in range(self.ndim))
        maxs = tuple(float(np.nanmax(self.vertices[:, i])) for i in range(self.ndim))
        return mins + maxs

    def cell_centroids(self) -> tuple[np.ndarray, np.ndarray]:
        """Per-cell ``(x, y)`` mean of the cell vertices.

        The cell centers the solvers read are ``PlanarCellMesh.centers``, the
        Voronoi generators for a Voronoi mesh.
        """
        conn = self.flat_connectivity
        verts = self.vertices
        xs = np.empty(self.n_cells, dtype=float)
        ys = np.empty(self.n_cells, dtype=float)
        for ic in range(self.n_cells):
            nodes = conn[ic][conn[ic] >= 0]
            xs[ic] = float(verts[nodes, 0].mean())
            ys[ic] = float(verts[nodes, 1].mean())
        return xs, ys

    def with_cell_data(self, **fields: np.ndarray) -> HydroMesh:
        """Return a new mesh with validated per-cell arrays added.

        An array holds one value per cell, or one row per cell with several
        components. The method preserves immutability of the original mesh and
        therefore behaves as a light builder around the frozen dataclass.
        """
        merged = dict(self.cell_data)
        for key, arr in fields.items():
            arr = np.asarray(arr)
            per_cell = arr.ndim == 2 and arr.shape[0] == self.n_cells
            if not per_cell and arr.reshape(-1).size != self.n_cells:
                raise ValueError(
                    f"cell_data['{key}'] must have {self.n_cells} values, "
                    f"got {arr.reshape(-1).size}"
                )
            merged[key] = arr if per_cell else arr.reshape(-1)
        return HydroMesh(
            vertices=self.vertices,
            cell_blocks=self.cell_blocks,
            cell_data=merged,
            point_data=self.point_data,
            structured_shape=self.structured_shape,
        )

    def with_point_data(self, **fields: np.ndarray) -> HydroMesh:
        """Return a new mesh with validated per-point arrays added."""
        merged = dict(self.point_data)
        for key, arr in fields.items():
            arr = np.asarray(arr)
            if arr.reshape(-1).size != self.n_nodes:
                raise ValueError(
                    f"point_data['{key}'] must have {self.n_nodes} values, "
                    f"got {arr.reshape(-1).size}"
                )
            merged[key] = arr.reshape(-1)
        return HydroMesh(
            vertices=self.vertices,
            cell_blocks=self.cell_blocks,
            cell_data=self.cell_data,
            point_data=merged,
            structured_shape=self.structured_shape,
        )

    def as_summary(self) -> dict[str, Any]:
        """Build a light JSON-serializable summary for diagnostics.

        The summary intentionally stays compact so that it can be embedded in
        logs, manifests, or small QA JSON files without dragging the full mesh.
        """
        return {
            "ndim": self.ndim,
            "n_nodes": self.n_nodes,
            "n_cells": self.n_cells,
            "cell_types": [ct.value for ct in self.cell_types],
            "is_structured": self.is_structured,
            "structured_shape": (list(self.structured_shape) if self.structured_shape else None),
            "bounds": list(self.bounds()),
            "cell_data_keys": sorted(self.cell_data),
            "point_data_keys": sorted(self.point_data),
        }

    def _repr_html_(self) -> str:
        bounds = self.bounds()
        rows: list[tuple[str, str]] = [
            ("ndim", str(self.ndim)),
            ("n_nodes", f"{self.n_nodes:,}"),
            ("n_cells", f"{self.n_cells:,}"),
            (
                "cell_types",
                ", ".join(ct.value for ct in self.cell_types) or "&mdash;",
            ),
            ("structured", "yes" if self.is_structured else "no"),
            (
                "structured_shape",
                str(self.structured_shape) if self.structured_shape else "&mdash;",
            ),
            (
                "bounds",
                ", ".join(f"{b:.3g}" for b in bounds) if bounds else "&mdash;",
            ),
            (
                "cell_data",
                ", ".join(sorted(self.cell_data)) or "&mdash;",
            ),
            (
                "point_data",
                ", ".join(sorted(self.point_data)) or "&mdash;",
            ),
        ]
        body = "".join(
            f"<tr><th style='text-align:left;padding-right:8px'>{k}</th><td>{v}</td></tr>"
            for k, v in rows
        )
        return (
            "<div><b>HydroMesh</b>"
            "<table style='font-size:0.85em;border-collapse:collapse'>"
            f"{body}</table></div>"
        )
