"""Field mesh over a ragged POLYGON HydroMesh (Voronoi/PEBI cells).

Bridges a :class:`~hydromodpy.spatial.mesh.hydro_mesh.HydroMesh` whose cells are
arbitrary n-gons into the field-mesh interface, so support-field sampling (K, Sy,
recharge, ...) works on Voronoi cells exactly as it does on triangles.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.spatial.field.core.field_mesh import BaseFieldMesh, MeshCell


class PolygonFieldMesh(BaseFieldMesh):
    """A field mesh backed by a ragged-polygon ``HydroMesh``."""

    _kind = "polygon"

    def __init__(self, hydro_mesh):
        verts = np.asarray(hydro_mesh.vertices, dtype=float)[:, :2]
        super().__init__(x_plot=verts[:, 0], y_plot=verts[:, 1])
        self._hydro = hydro_mesh
        self._verts = verts
        self._conn = hydro_mesh.flat_connectivity

    @property
    def n_cells(self) -> int:
        return int(self._hydro.n_cells)

    def iter_cells(self):
        x_centers, y_centers = self._hydro.cell_centroids()
        for idx in range(self.n_cells):
            nodes = np.asarray(self._conn[idx], dtype=int)
            yield MeshCell(
                index=int(idx),
                kind=self._kind,
                node_indices=tuple(int(v) for v in nodes),
                vertices=self._verts[nodes],
                centroid=(float(x_centers[idx]), float(y_centers[idx])),
            )

    def cell_centroids(self):
        return self._hydro.cell_centroids()

    def to_hydro_mesh(self):
        # The generic from_field_mesh adapter cannot rebuild a ragged POLYGON
        # block from fixed-arity node arrays; return the backing mesh directly.
        return self._hydro

    def to_cell_values(self, values):
        flat = np.asarray(values).reshape(-1)
        if flat.size != self.n_cells:
            raise ValueError("Polygon cell values must contain exactly one value per cell")
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
        from matplotlib.collections import PolyCollection

        polys = [self._verts[np.asarray(self._conn[i], dtype=int)] for i in range(self.n_cells)]
        collection = PolyCollection(
            polys,
            array=np.asarray(self.to_cell_values(cell_values), dtype=float),
            cmap=cmap,
            edgecolors="0.4" if show_mesh else "none",
            linewidths=0.15 if show_mesh else 0.0,
        )
        if vmin is not None or vmax is not None:
            collection.set_clim(vmin, vmax)
        ax.add_collection(collection)
        ax.autoscale_view()
        return collection
