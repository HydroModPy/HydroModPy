"""
Structured rectangular mesh for geology demos.

This mesh is defined on real projected coordinates (meters), unlike the
unit-square mesh used by the `square` case. It implements the generic
`BaseFieldMesh` contract so it can be used directly with:
1) `field.on_mesh(mesh, ...)`
2) `field_param.to_mesh_field(field_discretization)`
"""

from __future__ import annotations

import numpy as np

from hydromodpy.field.core.field_mesh import BaseFieldMesh, MeshCell


class GeologyStructuredMesh(BaseFieldMesh):
    """
    Structured quadrilateral mesh on one rectangular bounding box.
    """

    _kind = "structured_rect"

    def __init__(
        self,
        *,
        x_edges,
        y_edges,
        target_n_cells: int | None = None,
        resolution_hint: int | None = None,
    ):
        x_arr = np.asarray(x_edges, dtype=float).reshape(-1)
        y_arr = np.asarray(y_edges, dtype=float).reshape(-1)
        if x_arr.size < 2 or y_arr.size < 2:
            raise ValueError("x_edges and y_edges must each contain at least 2 values")
        if not np.all(np.diff(x_arr) > 0.0):
            raise ValueError("x_edges must be strictly increasing")
        if not np.all(np.diff(y_arr) > 0.0):
            raise ValueError("y_edges must be strictly increasing")

        x2d, y2d = np.meshgrid(x_arr, y_arr, indexing="xy")
        super().__init__(
            x_plot=x2d,
            y_plot=y2d,
            target_n_cells=target_n_cells,
            resolution_hint=resolution_hint,
        )

    @classmethod
    def from_bounds(cls, bounds, *, target_n_cells: int = 400):
        """
        Build a rectangular structured mesh from [xmin, ymin, xmax, ymax].
        """
        xmin, ymin, xmax, ymax = [float(v) for v in bounds]
        if not (np.isfinite(xmin) and np.isfinite(ymin) and np.isfinite(xmax) and np.isfinite(ymax)):
            raise ValueError("bounds must contain finite values")
        if xmax <= xmin or ymax <= ymin:
            raise ValueError("bounds must satisfy xmax > xmin and ymax > ymin")

        target = max(1, int(target_n_cells))
        width = xmax - xmin
        height = ymax - ymin
        ratio = width / height

        nx = max(2, int(np.round(np.sqrt(float(target) * ratio))) + 1)
        ny = max(2, int(np.round(np.sqrt(float(target) / ratio))) + 1)

        x_edges = np.linspace(xmin, xmax, nx, dtype=float)
        y_edges = np.linspace(ymin, ymax, ny, dtype=float)
        return cls(
            x_edges=x_edges,
            y_edges=y_edges,
            target_n_cells=target,
            resolution_hint=max(nx, ny),
        )

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
        from hydromodpy.mesh.plotting import plot_cell_values as _unified_plot

        values2d = np.asarray(self.to_cell_values(cell_values), dtype=float)
        return _unified_plot(
            ax,
            self.to_hydro_mesh(),
            values2d.reshape(-1),
            cmap=cmap,
            show_mesh=show_mesh,
            vmin=vmin,
            vmax=vmax,
        )
