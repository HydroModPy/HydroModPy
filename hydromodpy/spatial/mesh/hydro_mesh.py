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

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from hydromodpy.spatial.mesh.cell_types import CellType


@dataclass(frozen=True)
class CellBlock:
    """One homogeneous block of cells sharing the same geometry type.

    A mesh may contain several blocks (e.g. triangles + quads in a hybrid
    mesh, or wedges across multiple physical groups).  Most HydroModPy meshes
    carry a single block.
    """

    cell_type: CellType
    connectivity: np.ndarray  # (n_cells, nodes_per_cell), int

    def __post_init__(self) -> None:
        """Normalize and validate the homogeneous connectivity block."""
        ct = self.cell_type
        if not isinstance(ct, CellType):
            object.__setattr__(self, "cell_type", CellType.from_string(str(ct)))
            ct = self.cell_type
        conn = np.asarray(self.connectivity, dtype=int)
        if conn.ndim != 2 or conn.shape[1] != ct.nodes_per_cell:
            raise ValueError(
                f"{ct.value} connectivity must have shape (n_cells, {ct.nodes_per_cell}), "
                f"got {conn.shape}"
            )
        object.__setattr__(self, "connectivity", conn.copy())

    @property
    def n_cells(self) -> int:
        return int(self.connectivity.shape[0])


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
            if np.any(block.connectivity < 0) or np.any(block.connectivity >= n_nodes):
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
        return int(self.vertices.shape[0])

    @property
    def n_cells(self) -> int:
        return sum(b.n_cells for b in self.cell_blocks)

    @property
    def is_structured(self) -> bool:
        return self.structured_shape is not None

    @property
    def cell_types(self) -> tuple[CellType, ...]:
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
        """Concatenate connectivity across all blocks.

        This helper is convenient when a downstream consumer only cares about
        the flattened cell stream and has already ensured that mixed cell types
        are acceptable.
        """
        if len(self.cell_blocks) == 1:
            return np.asarray(self.cell_blocks[0].connectivity, dtype=int)
        return np.vstack([b.connectivity for b in self.cell_blocks]).astype(int, copy=False)

    def bounds(self) -> tuple[float, ...]:
        """Return ``(xmin, ymin, [zmin,] xmax, ymax, [zmax])``."""
        mins = tuple(float(np.nanmin(self.vertices[:, i])) for i in range(self.ndim))
        maxs = tuple(float(np.nanmax(self.vertices[:, i])) for i in range(self.ndim))
        return mins + maxs

    def with_cell_data(self, **fields: np.ndarray) -> HydroMesh:
        """Return a new mesh with validated per-cell arrays added.

        The method preserves immutability of the original mesh and therefore
        behaves as a light builder around the frozen dataclass.
        """
        merged = dict(self.cell_data)
        for key, arr in fields.items():
            arr = np.asarray(arr)
            if arr.reshape(-1).size != self.n_cells:
                raise ValueError(
                    f"cell_data['{key}'] must have {self.n_cells} values, "
                    f"got {arr.reshape(-1).size}"
                )
            merged[key] = arr.reshape(-1)
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
