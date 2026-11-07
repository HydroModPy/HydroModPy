"""Draw one value per cell of a planar mesh on a matplotlib axes.

A regular grid is drawn with ``pcolormesh``, triangles with ``tripcolor`` and
any other cells as polygons.
"""

from __future__ import annotations

import matplotlib.collections as mcollections
import matplotlib.tri as mtri
import numpy as np

from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.geometry import padded_rows
from hydromodpy.spatial.mesh.model.hydro_mesh import HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

__all__ = ("plot_cell_values",)


def plot_cell_values(
    ax,
    mesh: PlanarCellMesh | HydroMesh,
    values: np.ndarray,
    *,
    cmap: str = "viridis",
    show_mesh: bool = False,
    vmin: float | None = None,
    vmax: float | None = None,
):
    """Plot one scalar value per cell of a planar mesh and return the mappable.

    ``mesh`` is a ``PlanarCellMesh`` or a planar ``HydroMesh`` of one cell type,
    in one block or several. The mappable feeds a colorbar.
    """
    hydro_mesh = mesh.mesh if isinstance(mesh, PlanarCellMesh) else mesh
    if hydro_mesh.ndim != 2:
        raise ValueError("plot_cell_values only supports 2D meshes")

    vals = np.asarray(values, dtype=float).reshape(-1)
    if vals.size != hydro_mesh.n_cells:
        raise ValueError(f"Expected {hydro_mesh.n_cells} values, got {vals.size}")

    verts = np.asarray(hydro_mesh.vertices, dtype=float)
    cell_type = hydro_mesh.single_cell_type
    structured_shape = mesh.structured_shape
    rows = _cell_rows(mesh)

    if cell_type == CellType.QUADRILATERAL and structured_shape is not None:
        return _plot_structured(
            ax,
            verts,
            vals,
            structured_shape,
            cmap=cmap,
            show_mesh=show_mesh,
            vmin=vmin,
            vmax=vmax,
        )

    if cell_type == CellType.TRIANGLE:
        return _plot_triangles(
            ax,
            verts,
            rows,
            vals,
            cmap=cmap,
            show_mesh=show_mesh,
            vmin=vmin,
            vmax=vmax,
        )

    return _plot_polygons(
        ax,
        verts,
        rows,
        vals,
        cmap=cmap,
        show_mesh=show_mesh,
        vmin=vmin,
        vmax=vmax,
    )


def _cell_rows(mesh: PlanarCellMesh | HydroMesh) -> np.ndarray:
    """The cells as one ``(n_cells, k)`` table of node ids, ``-1`` in the free slots."""
    if isinstance(mesh, PlanarCellMesh):
        return np.asarray(mesh.connectivity_rows)
    return padded_rows(mesh.flat_connectivity, n_nodes=mesh.n_nodes)


def _plot_structured(ax, verts, vals, shape, *, cmap, show_mesh, vmin, vmax):
    """Render a structured quadrilateral mesh with ``pcolormesh``."""
    nrow, ncol = shape
    x = verts[:, 0].reshape(nrow + 1, ncol + 1)
    y = verts[:, 1].reshape(nrow + 1, ncol + 1)
    z = vals.reshape(nrow, ncol)
    mappable = ax.pcolormesh(
        x,
        y,
        z,
        shading="flat",
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
    )
    if show_mesh:
        for j in range(nrow + 1):
            ax.plot(x[j, :], y[j, :], color="0.75", lw=0.35)
        for i in range(ncol + 1):
            ax.plot(x[:, i], y[:, i], color="0.75", lw=0.35)
    ax.set_aspect("equal")
    ax.set_xlim(float(x.min()), float(x.max()))
    ax.set_ylim(float(y.min()), float(y.max()))
    return mappable


def _plot_triangles(ax, verts, rows, vals, *, cmap, show_mesh, vmin, vmax):
    """Render a purely triangular mesh with Matplotlib triangulation support."""
    tri = mtri.Triangulation(verts[:, 0], verts[:, 1], triangles=rows)
    mappable = ax.tripcolor(
        tri,
        facecolors=vals,
        shading="flat",
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
    )
    if show_mesh:
        ax.triplot(tri, color="0.70", lw=0.35)
    ax.set_aspect("equal")
    ax.set_xlim(float(verts[:, 0].min()), float(verts[:, 0].max()))
    ax.set_ylim(float(verts[:, 1].min()), float(verts[:, 1].max()))
    return mappable


def _plot_polygons(ax, verts, rows, vals, *, cmap, show_mesh, vmin, vmax):
    """Render quadrilaterals and polygons as one ``PolyCollection``."""
    polygons = [verts[row[row >= 0]] for row in rows]
    edge_color = "0.70" if show_mesh else "face"
    edge_width = 0.35 if show_mesh else 0.0
    collection = mcollections.PolyCollection(
        polygons,
        cmap=cmap,
        linewidths=edge_width,
        edgecolors=edge_color,
    )
    collection.set_array(vals)
    if vmin is not None or vmax is not None:
        collection.set_clim(vmin=vmin, vmax=vmax)
    ax.add_collection(collection)
    ax.set_aspect("equal")
    ax.set_xlim(float(verts[:, 0].min()), float(verts[:, 0].max()))
    ax.set_ylim(float(verts[:, 1].min()), float(verts[:, 1].max()))
    return collection
