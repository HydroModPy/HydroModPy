"""Build the final matplotlib figure for the standalone mesh viewer.

This module intentionally stays at orchestration level. Geometry preparation
helpers live in ``mesh.display.geometry`` and concrete panel renderers live in
``mesh.display.panels``.

If you are reading the rendering stack for the first time, start here before
opening the more specialized helper modules.
"""

from __future__ import annotations

from mesh.bundle_contracts import MeshBundleLike
from mesh.display.geometry import (
    build_node_xy_map,
    has_continuous_node_topography,
)
from mesh.display.panels import (
    build_default_panel_title,
    load_matplotlib,
    plot_continuous_topography_panel,
    plot_mesh_panel,
)
from mesh.schema import VisualizationConfig


def build_visualization_figure(
    mesh: MeshBundleLike,
    *,
    config: VisualizationConfig,
):
    """Build the final visualization figure from one loaded bundle.

    This is the recommended rendering entry point for callers that already own
    a loaded mesh bundle and a resolved ``VisualizationConfig``.
    """

    matplotlib, plt, LineCollection, PolyCollection, Patch = load_matplotlib(
        show_window=config.show_window
    )
    panel_count = 2 if config.plot.show_topography_panel else 1
    figure, axes = plt.subplots(
        1,
        panel_count,
        figsize=config.plot.figure_size,
        dpi=config.plot.dpi,
    )
    axes = [axes] if panel_count == 1 else list(axes)
    node_xy_map = build_node_xy_map(mesh)

    left_title = config.plot.title
    if left_title is None:
        left_title = build_default_panel_title(
            heading="Vue structurelle du maillage",
            field_name=f"color_field = {config.plot.color_field}",
        )

    plot_mesh_panel(
        axes[0],
        mesh=mesh,
        node_xy_map=node_xy_map,
        plot_config=config.plot,
        color_field=config.plot.color_field,
        color_map=config.plot.color_map,
        title=left_title,
        show_info_box=True,
        matplotlib=matplotlib,
        plt=plt,
        LineCollection=LineCollection,
        PolyCollection=PolyCollection,
        Patch=Patch,
    )

    if config.plot.show_topography_panel:
        right_title = config.plot.topography_title
        if right_title is None:
            right_title = build_default_panel_title(
                heading="Vue topographique continue",
                field_name=f"topography_field = {config.plot.topography_field}",
            )

        has_continuous_render = plot_continuous_topography_panel(
            axes[1],
            mesh=mesh,
            node_xy_map=node_xy_map,
            plot_config=config.plot,
            color_map=config.plot.topography_cmap,
            title=right_title,
            plt=plt,
            LineCollection=LineCollection,
        )

        if not has_continuous_render:
            plot_mesh_panel(
                axes[1],
                mesh=mesh,
                node_xy_map=node_xy_map,
                plot_config=config.plot,
                color_field=config.plot.topography_field,
                color_map=config.plot.topography_cmap,
                title=f"{right_title}\nrepli par cellule",
                show_info_box=False,
                matplotlib=matplotlib,
                plt=plt,
                LineCollection=LineCollection,
                PolyCollection=PolyCollection,
                Patch=Patch,
            )

    figure.tight_layout()
    return figure


__all__ = [
    "build_visualization_figure",
    "has_continuous_node_topography",
]
