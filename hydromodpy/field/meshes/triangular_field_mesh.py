"""Concrete triangular planar meshes shared across field workflows."""

from __future__ import annotations

import matplotlib.tri as mtri
import numpy as np

from hydromodpy.field.core.field_mesh import BaseFieldMesh, MeshCell


class _TriangularBaseFieldMesh(BaseFieldMesh):
    """Common behavior for triangular meshes."""

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
        self.triangulation: mtri.Triangulation = triangulation

    def _require_triangulation(self) -> mtri.Triangulation:
        triangulation = self.triangulation
        if triangulation is None:
            raise RuntimeError("triangulation is not initialized")
        return triangulation

    @property
    def n_cells(self) -> int:
        triangulation = self._require_triangulation()
        return int(triangulation.triangles.shape[0])

    def iter_cells(self):
        triangulation = self._require_triangulation()
        x = np.asarray(triangulation.x, dtype=float)
        y = np.asarray(triangulation.y, dtype=float)
        for idx, nodes in enumerate(np.asarray(triangulation.triangles, dtype=int)):
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
        from hydromodpy.mesh.plotting import plot_cell_values as _unified_plot

        values1d = np.asarray(self.to_cell_values(cell_values), dtype=float)
        return _unified_plot(
            ax,
            self.to_hydro_mesh(),
            values1d,
            cmap=cmap,
            show_mesh=show_mesh,
            vmin=vmin,
            vmax=vmax,
        )


class TriangularStructuredFieldMesh(_TriangularBaseFieldMesh):
    """Triangular mesh from structured node grid."""

    _kind = "triangular_structured"


class TriangularUnstructuredFieldMesh(_TriangularBaseFieldMesh):
    """Triangular mesh from irregular node cloud."""

    _kind = "triangular_unstructured"
