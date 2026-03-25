"""Unified plotting dispatch for HydroMesh.

A single ``plot_cell_values`` function that picks the best matplotlib
rendering strategy depending on the mesh topology (structured → pcolormesh,
triangles → tripcolor, polygons → PolyCollection).
"""

from __future__ import annotations

import matplotlib.collections as mcollections
import matplotlib.tri as mtri
import numpy as np

from hydromodpy.spatial.mesh.cell_types import CellType
from hydromodpy.spatial.mesh.hydro_mesh import HydroMesh


def plot_cell_values(
    ax,
    hydro_mesh: HydroMesh,
    values: np.ndarray,
    *,
    cmap: str = "viridis",
    show_mesh: bool = False,
    vmin: float | None = None,
    vmax: float | None = None,
):
    """Plot one scalar value per cell on a matplotlib Axes.

    Parameters
    ----------
    ax : matplotlib Axes
    hydro_mesh : HydroMesh (2D only)
    values : array-like, one value per cell
    cmap, show_mesh, vmin, vmax : styling options

    Returns
    -------
    matplotlib ScalarMappable (for colorbar)
    """
    if hydro_mesh.ndim != 2:
        raise ValueError("plot_cell_values only supports 2D meshes")

    vals = np.asarray(values, dtype=float).reshape(-1)
    if vals.size != hydro_mesh.n_cells:
        raise ValueError(
            f"Expected {hydro_mesh.n_cells} values, got {vals.size}"
        )

    verts = np.asarray(hydro_mesh.vertices, dtype=float)
    ct = hydro_mesh.single_cell_type
    conn = hydro_mesh.flat_connectivity

    if (
        hydro_mesh.is_structured
        and ct == CellType.QUADRILATERAL
        and hydro_mesh.structured_shape is not None
    ):
        return _plot_structured(
            ax, verts, vals, hydro_mesh.structured_shape,
            cmap=cmap, show_mesh=show_mesh, vmin=vmin, vmax=vmax,
        )

    if ct == CellType.TRIANGLE:
        return _plot_triangles(
            ax, verts, conn, vals,
            cmap=cmap, show_mesh=show_mesh, vmin=vmin, vmax=vmax,
        )

    return _plot_polygons(
        ax, verts, conn, vals,
        cmap=cmap, show_mesh=show_mesh, vmin=vmin, vmax=vmax,
    )


def _plot_structured(ax, verts, vals, shape, *, cmap, show_mesh, vmin, vmax):
    """Render a structured quadrilateral mesh with ``pcolormesh``."""
    nrow, ncol = shape
    x = verts[:, 0].reshape(nrow + 1, ncol + 1)
    y = verts[:, 1].reshape(nrow + 1, ncol + 1)
    z = vals.reshape(nrow, ncol)
    mappable = ax.pcolormesh(
        x, y, z, shading="flat", cmap=cmap, vmin=vmin, vmax=vmax,
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


def _plot_triangles(ax, verts, conn, vals, *, cmap, show_mesh, vmin, vmax):
    """Render a purely triangular mesh with Matplotlib triangulation support."""
    tri = mtri.Triangulation(verts[:, 0], verts[:, 1], triangles=conn)
    mappable = ax.tripcolor(
        tri, facecolors=vals, shading="flat",
        cmap=cmap, vmin=vmin, vmax=vmax,
    )
    if show_mesh:
        ax.triplot(tri, color="0.70", lw=0.35)
    ax.set_aspect("equal")
    ax.set_xlim(float(verts[:, 0].min()), float(verts[:, 0].max()))
    ax.set_ylim(float(verts[:, 1].min()), float(verts[:, 1].max()))
    return mappable


def _plot_polygons(ax, verts, conn, vals, *, cmap, show_mesh, vmin, vmax):
    """Fallback renderer for generic polygonal 2D meshes."""
    polygons = [verts[nodes] for nodes in conn]
    edge_color = "0.70" if show_mesh else "face"
    edge_width = 0.35 if show_mesh else 0.0
    collection = mcollections.PolyCollection(
        polygons, cmap=cmap, linewidths=edge_width, edgecolors=edge_color,
    )
    collection.set_array(vals)
    if vmin is not None or vmax is not None:
        collection.set_clim(vmin=vmin, vmax=vmax)
    ax.add_collection(collection)
    ax.set_aspect("equal")
    ax.set_xlim(float(verts[:, 0].min()), float(verts[:, 0].max()))
    ax.set_ylim(float(verts[:, 1].min()), float(verts[:, 1].max()))
    return collection
