"""
Square-domain mesh implementations for field examples.

This module provides concrete meshes (structured/triangular) for the unit
square and a concrete factory `FieldMeshSquare`.
"""

from __future__ import annotations

from typing import Any, Mapping

import matplotlib.tri as mtri
import numpy as np

from hydromodpy.field.core.field_mesh import BaseFieldMesh, FieldMesh, MeshCell


SUPPORTED_MESH_KINDS = ("structured", "triangular_structured", "triangular_unstructured")


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


class StructuredFieldMesh(BaseFieldMesh):
    """
    Structured quadrilateral mesh over [0, 1]x[0, 1].
    """

    _kind = "structured"

    @property
    def n_cells(self) -> int:
        ny, nx = self.shape
        return max(ny - 1, 0) * max(nx - 1, 0)

    def iter_cells(self):
        ny, nx = self.shape
        idx = 0
        for j in range(ny - 1):
            for i in range(nx - 1):
                n00 = j * nx + i
                n10 = j * nx + (i + 1)
                n11 = (j + 1) * nx + (i + 1)
                n01 = (j + 1) * nx + i
                vertices = np.array(
                    [
                        [self.x_plot[j, i], self.y_plot[j, i]],
                        [self.x_plot[j, i + 1], self.y_plot[j, i + 1]],
                        [self.x_plot[j + 1, i + 1], self.y_plot[j + 1, i + 1]],
                        [self.x_plot[j + 1, i], self.y_plot[j + 1, i]],
                    ],
                    dtype=float,
                )
                centroid = (float(vertices[:, 0].mean()), float(vertices[:, 1].mean()))
                yield MeshCell(
                    index=idx,
                    kind="quadrilateral",
                    node_indices=(n00, n10, n11, n01),
                    vertices=vertices,
                    centroid=centroid,
                )
                idx += 1

    def cell_centroids(self):
        cx = np.array([cell.centroid[0] for cell in self.cells], dtype=float)
        cy = np.array([cell.centroid[1] for cell in self.cells], dtype=float)
        ny, nx = self.shape
        return cx.reshape((ny - 1, nx - 1)), cy.reshape((ny - 1, nx - 1))

    def to_cell_values(self, values):
        arr = np.asarray(values)
        ny, nx = self.shape
        expected_shape = (ny - 1, nx - 1)
        if arr.ndim == 2:
            if arr.shape != expected_shape:
                raise ValueError("Structured cell values must match shape (ny-1, nx-1)")
            return arr
        flat = arr.reshape(-1)
        if flat.size != self.n_cells:
            raise ValueError("Structured cell values must contain one value per cell")
        return flat.reshape(expected_shape)

    def plot_cell_values(
        self,
        ax,
        cell_values,
        *,
        cmap="viridis",
        show_mesh=False,
        vmin=None,
        vmax=None,
    ):
        values2d = np.asarray(self.to_cell_values(cell_values), dtype=float)
        mappable = ax.pcolormesh(
            self.x_plot,
            self.y_plot,
            values2d,
            shading="flat",
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
        )
        if show_mesh:
            for j in range(self.y_plot.shape[0]):
                ax.plot(self.x_plot[j, :], self.y_plot[j, :], color="0.75", lw=0.35)
            for i in range(self.x_plot.shape[1]):
                ax.plot(self.x_plot[:, i], self.y_plot[:, i], color="0.75", lw=0.35)
        ax.set_aspect("equal")
        ax.set_xlim(0.0, 1.0)
        ax.set_ylim(0.0, 1.0)
        return mappable


class _TriangularBaseFieldMesh(BaseFieldMesh):
    """
    Common behavior for triangular meshes.
    """

    def __init__(
        self,
        *,
        x_plot,
        y_plot,
        triangulation: mtri.Triangulation,
        target_n_cells: int | None = None,
        resolution_hint: int | None = None,
        seed: int | None = None,
    ):
        if triangulation is None:
            raise ValueError("triangular mesh requires triangulation")
        super().__init__(
            x_plot=x_plot,
            y_plot=y_plot,
            target_n_cells=target_n_cells,
            resolution_hint=resolution_hint,
            seed=seed,
        )
        self.triangulation = triangulation

    @property
    def n_cells(self) -> int:
        return int(self.triangulation.triangles.shape[0])

    def iter_cells(self):
        x = np.asarray(self.triangulation.x, dtype=float)
        y = np.asarray(self.triangulation.y, dtype=float)
        for idx, nodes in enumerate(np.asarray(self.triangulation.triangles, dtype=int)):
            vertices = np.column_stack((x[nodes], y[nodes]))
            centroid = (float(vertices[:, 0].mean()), float(vertices[:, 1].mean()))
            yield MeshCell(
                index=int(idx),
                kind="triangle",
                node_indices=tuple(int(v) for v in nodes),
                vertices=vertices,
                centroid=centroid,
            )

    def cell_centroids(self):
        cx = np.array([cell.centroid[0] for cell in self.cells], dtype=float)
        cy = np.array([cell.centroid[1] for cell in self.cells], dtype=float)
        return cx, cy

    def to_cell_values(self, values):
        arr = np.asarray(values)
        flat = arr.reshape(-1)
        if flat.size != self.n_cells:
            raise ValueError("Triangular cell values must contain one value per cell")
        return flat

    def plot_cell_values(
        self,
        ax,
        cell_values,
        *,
        cmap="viridis",
        show_mesh=False,
        vmin=None,
        vmax=None,
    ):
        values1d = np.asarray(self.to_cell_values(cell_values), dtype=float)
        mappable = ax.tripcolor(
            self.triangulation,
            facecolors=values1d,
            shading="flat",
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
        )
        if show_mesh:
            ax.triplot(self.triangulation, color="0.70", lw=0.35)
        ax.set_aspect("equal")
        ax.set_xlim(0.0, 1.0)
        ax.set_ylim(0.0, 1.0)
        return mappable


class TriangularStructuredFieldMesh(_TriangularBaseFieldMesh):
    """
    Triangular mesh from structured node grid.
    """

    _kind = "triangular_structured"


class TriangularUnstructuredFieldMesh(_TriangularBaseFieldMesh):
    """
    Triangular mesh from irregular node cloud.
    """

    _kind = "triangular_unstructured"


class FieldMeshSquare(FieldMesh):
    """
    Concrete factory for unit-square meshes.
    """

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
        """
        Build mesh from mapping.

        Expected keys
        -------------
        - `target_n_cells` (preferred),
        - aliases: `approx_n_cells`, `target_cell_count`,
        - `kind` or `mesh_kind`:
          "structured" | "triangular_structured" | "triangular_unstructured"
        """
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
