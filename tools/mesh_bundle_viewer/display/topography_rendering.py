"""Topography-panel rendering for the standalone mesh visualization package."""

from __future__ import annotations

from collections.abc import Mapping

from ..bundle_contracts import MeshBundleLike
from .geometry import (
    build_triangulation_inputs,
    format_axes,
    get_node_topography_values,
)
from .overlay_rendering import plot_overlays
from .rendering_common import plot_cell_annotations
from ..schema import PlotConfig


def plot_continuous_topography_panel(
    ax,
    *,
    mesh: MeshBundleLike,
    node_xy_map: Mapping[int, tuple[float, float]],
    plot_config: PlotConfig,
    color_map: str,
    title: str,
    plt,
    LineCollection,
) -> bool:
    """Render the continuous topography panel from nodal elevations."""

    from matplotlib import tri as mtri

    x_values, y_values, triangles = build_triangulation_inputs(mesh)
    if not triangles:
        return False

    z_values, valid_mask = get_node_topography_values(mesh)
    triangle_mask = [
        not bool(valid_mask[i0] and valid_mask[i1] and valid_mask[i2])
        for i0, i1, i2 in triangles
    ]
    if all(triangle_mask):
        return False

    triangulation = mtri.Triangulation(x_values, y_values, triangles)
    if any(triangle_mask):
        triangulation.set_mask(triangle_mask)

    surface = ax.tripcolor(
        triangulation,
        z_values,
        cmap=color_map,
        shading="gouraud",
    )
    plt.colorbar(surface, ax=ax, fraction=0.04, pad=0.02)

    if plot_config.show_mesh_edges:
        ax.triplot(
            triangulation,
            color=str(plot_config.mesh_edge_color),
            linewidth=float(plot_config.mesh_edge_linewidth),
        )

    plot_overlays(
        ax,
        mesh=mesh,
        node_xy_map=node_xy_map,
        plot_config=plot_config,
        LineCollection=LineCollection,
    )
    plot_cell_annotations(ax, mesh=mesh, plot_config=plot_config)

    format_axes(ax, node_xy_map=node_xy_map)
    ax.set_title(title)
    return True


__all__ = [
    "plot_continuous_topography_panel",
]

