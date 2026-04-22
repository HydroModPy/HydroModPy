"""Public panel-level rendering facade for the standalone mesh viewer.

This module intentionally re-exports a small panel API while the lower-level
cell, overlay, and topography renderers live in dedicated helper modules.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..bundle_contracts import MeshBundleLike
from .cell_rendering import (
    plot_categorical_cells,
    plot_numeric_cells,
)
from .geometry import (
    build_cell_polygons,
    format_axes,
    get_categorical_cell_values,
    get_numeric_cell_values,
)
from .overlay_rendering import plot_overlays
from .rendering_common import (
    build_default_panel_title,
    get_mesh_edge_style,
    load_matplotlib,
    plot_cell_annotations,
)
from .topography_rendering import plot_continuous_topography_panel
from ..schema import NUMERIC_COLOR_FIELDS, PlotConfig


def plot_mesh_panel(
    ax,
    *,
    mesh: MeshBundleLike,
    node_xy_map: Mapping[int, tuple[float, float]],
    plot_config: PlotConfig,
    color_field: str,
    color_map: str,
    title: str,
    show_info_box: bool,
    matplotlib,
    plt,
    LineCollection,
    PolyCollection,
    Patch,
) -> None:
    """Render the main cell-based panel.

    Most callers should not import lower-level cell or overlay helpers
    directly; this function is the stable panel-oriented entry point.
    """

    from .geometry import build_info_text

    mesh_edge_color, mesh_edge_linewidth = get_mesh_edge_style(plot_config)
    polygons = build_cell_polygons(mesh, node_xy_map=node_xy_map)

    if color_field in NUMERIC_COLOR_FIELDS:
        plot_numeric_cells(
            ax,
            polygons=polygons,
            values=get_numeric_cell_values(mesh, color_field),
            color_map=color_map,
            mesh_edge_color=mesh_edge_color,
            mesh_edge_linewidth=mesh_edge_linewidth,
            PolyCollection=PolyCollection,
            plt=plt,
        )
    else:
        plot_categorical_cells(
            ax,
            polygons=polygons,
            values=get_categorical_cell_values(mesh, color_field),
            color_map=color_map,
            mesh_edge_color=mesh_edge_color,
            mesh_edge_linewidth=mesh_edge_linewidth,
            matplotlib=matplotlib,
            PolyCollection=PolyCollection,
            Patch=Patch,
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

    if show_info_box:
        ax.text(
            0.99,
            0.01,
            build_info_text(mesh),
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=9,
            bbox={
                "boxstyle": "round",
                "facecolor": "white",
                "alpha": 0.9,
                "edgecolor": "0.7",
            },
        )


__all__ = [
    "build_default_panel_title",
    "get_mesh_edge_style",
    "load_matplotlib",
    "plot_continuous_topography_panel",
    "plot_mesh_panel",
]
