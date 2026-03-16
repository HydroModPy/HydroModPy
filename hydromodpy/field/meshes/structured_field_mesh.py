"""Concrete structured planar meshes shared across field workflows."""

from __future__ import annotations

import numpy as np

from hydromodpy.field.core.field_mesh import BaseFieldMesh, MeshCell


class StructuredFieldMesh(BaseFieldMesh):
    """Structured quadrilateral mesh over arbitrary XY coordinates."""

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
