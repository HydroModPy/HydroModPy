"""Concrete structured planar meshes shared across field workflows."""

from __future__ import annotations

import numpy as np

from hydromodpy.field.core.field_mesh import BaseFieldMesh, MeshCell


def _set_axes_limits_from_mesh(ax, *, x_plot, y_plot) -> None:
    """Set axis limits from mesh coordinates without assuming a unit square."""
    x_arr = np.asarray(x_plot, dtype=float)
    y_arr = np.asarray(y_plot, dtype=float)
    ax.set_aspect("equal")
    ax.set_xlim(float(np.nanmin(x_arr)), float(np.nanmax(x_arr)))
    ax.set_ylim(float(np.nanmin(y_arr)), float(np.nanmax(y_arr)))


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
        _set_axes_limits_from_mesh(ax, x_plot=self.x_plot, y_plot=self.y_plot)
        return mappable
