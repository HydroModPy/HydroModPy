"""Square-domain mesh factory built on top of generic reusable meshes."""

from __future__ import annotations

from typing import Any, Mapping

import matplotlib.tri as mtri
import numpy as np

from hydromodpy.spatial.field.core.field_mesh import BaseFieldMesh, FieldMesh
from hydromodpy.spatial.field.meshes import (
    StructuredFieldMesh,
    TriangularStructuredFieldMesh,
    TriangularUnstructuredFieldMesh,
)

SUPPORTED_MESH_KINDS = (
    "structured",
    "triangular_structured",
    "triangular_unstructured",
)


def _build_unit_square_grid(n_grid: int):
    n_grid = int(n_grid)
    if n_grid <= 2:
        raise ValueError("n_grid must be > 2")
    xy = np.linspace(0.0, 1.0, n_grid, dtype=float)
    return np.meshgrid(xy, xy, indexing="xy")


def _axis_points_from_target_cells(target_n_cells: int, *, mesh_kind: str):
    target = max(1, int(target_n_cells))
    if mesh_kind == "structured":
        base = float(target)
    else:
        # Triangular mesh: n_triangles ~= 2*(n_axis-1)^2
        base = float(target) / 2.0
    return max(3, int(np.round(np.sqrt(base))) + 1)


def _build_unstructured_boundary(n_per_edge: int):
    edge = np.linspace(0.0, 1.0, n_per_edge, dtype=float)
    xb = np.concatenate(
        [
            edge,
            np.ones(n_per_edge - 1, dtype=float),
            edge[-2::-1],
            np.zeros(n_per_edge - 2, dtype=float),
        ]
    )
    yb = np.concatenate(
        [
            np.zeros(n_per_edge, dtype=float),
            edge[1:],
            np.ones(n_per_edge - 1, dtype=float),
            edge[-2:0:-1],
        ]
    )
    return xb, yb


def _build_unstructured_points(target_n_cells: int, *, seed: int):
    target = max(8, int(target_n_cells))
    n_per_edge = max(3, int(np.ceil(np.sqrt(float(target)) / 2.0)) + 1)
    xb, yb = _build_unstructured_boundary(n_per_edge)
    n_boundary = int(xb.size)

    # Planar triangulation heuristic: n_triangles ~= 2*n_points - 2 - n_boundary
    n_interior = max(0, int(np.ceil((float(target) - float(n_boundary) + 2.0) / 2.0)))
    rng = np.random.default_rng(int(seed))
    if n_interior > 0:
        xi = rng.uniform(1e-6, 1.0 - 1e-6, size=n_interior)
        yi = rng.uniform(1e-6, 1.0 - 1e-6, size=n_interior)
        x = np.concatenate([xb, xi])
        y = np.concatenate([yb, yi])
    else:
        x = xb
        y = yb
    return x, y, n_per_edge


class FieldMeshSquare(FieldMesh):
    """Concrete factory for unit-square meshes."""

    @classmethod
    def from_unit_square(
        cls,
        *,
        target_n_cells: int,
        mesh_kind: str = "structured",
        seed: int = 42,
    ) -> BaseFieldMesh:
        kind_key = str(mesh_kind).strip().lower()
        target = max(1, int(target_n_cells))

        if kind_key == "structured":
            n_axis = _axis_points_from_target_cells(target, mesh_kind=kind_key)
            x2d, y2d = _build_unit_square_grid(n_axis)
            return StructuredFieldMesh(
                x_plot=x2d,
                y_plot=y2d,
                target_n_cells=target,
                resolution_hint=n_axis,
            )

        if kind_key == "triangular_structured":
            n_axis = _axis_points_from_target_cells(target, mesh_kind=kind_key)
            x2d, y2d = _build_unit_square_grid(n_axis)
            triang = mtri.Triangulation(x2d.ravel(), y2d.ravel())
            return TriangularStructuredFieldMesh(
                x_plot=x2d,
                y_plot=y2d,
                triangulation=triang,
                target_n_cells=target,
                resolution_hint=n_axis,
            )

        if kind_key == "triangular_unstructured":
            x, y, n_per_edge = _build_unstructured_points(target, seed=int(seed))
            triang = mtri.Triangulation(x, y)
            return TriangularUnstructuredFieldMesh(
                x_plot=x,
                y_plot=y,
                triangulation=triang,
                target_n_cells=target,
                resolution_hint=n_per_edge,
                seed=int(seed),
            )

        allowed = ", ".join(SUPPORTED_MESH_KINDS)
        raise ValueError(f"Unsupported mesh kind '{mesh_kind}'. Allowed: {allowed}")

    @classmethod
    def from_dict(cls, config: Mapping[str, Any]) -> BaseFieldMesh:
        """Build one unit-square mesh from a plain mapping."""
        if not isinstance(config, Mapping):
            raise TypeError("config must be a mapping")
        mesh_kind = str(config.get("mesh_kind", config.get("kind", "structured")))

        target_n_cells = None
        for key in ("target_n_cells", "approx_n_cells", "target_cell_count"):
            if key in config:
                target_n_cells = int(config[key])
                break

        if target_n_cells is None:
            # Backward compatibility with old n_grid config.
            if "n_grid" not in config:
                raise KeyError(
                    "Mesh config requires 'target_n_cells' "
                    "(aliases: 'approx_n_cells', 'target_cell_count')"
                )
            n_grid = int(config["n_grid"])
            if n_grid <= 2:
                raise ValueError("n_grid must be > 2")
            kind_key = str(mesh_kind).strip().lower()
            if kind_key == "structured":
                target_n_cells = (n_grid - 1) ** 2
            else:
                target_n_cells = 2 * (n_grid - 1) ** 2

        seed = int(config.get("seed", 42))
        return cls.from_unit_square(
            target_n_cells=target_n_cells,
            mesh_kind=mesh_kind,
            seed=seed,
        )
