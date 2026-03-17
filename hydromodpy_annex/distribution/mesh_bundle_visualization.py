"""Visualization helpers for the annex mesh-bundle viewer."""

from __future__ import annotations

from collections.abc import Mapping

from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
)

from hydromodpy_annex.distribution.mesh_bundle_viewer_io import (
    MeshBundlePlotConfig,
    MeshBundleViewerConfig,
    NUMERIC_COLOR_FIELDS,
)


def _load_matplotlib(*, show_plot: bool):
    import matplotlib

    if not show_plot:
        try:
            matplotlib.use("Agg", force=True)
        except Exception:
            pass

    from matplotlib import pyplot as plt
    from matplotlib.collections import LineCollection, PolyCollection
    from matplotlib.colors import Normalize
    from matplotlib.patches import Patch

    return matplotlib, plt, LineCollection, PolyCollection, Normalize, Patch


def _node_xy_map(bundle: CatchmentMeshBundle) -> dict[int, tuple[float, float]]:
    return {
        int(node.node_id): (float(node.x), float(node.y))
        for node in bundle.nodes
    }


def _cell_polygons(bundle: CatchmentMeshBundle) -> list[list[tuple[float, float]]]:
    node_map = _node_xy_map(bundle)
    polygons: list[list[tuple[float, float]]] = []
    for cell in bundle.cells:
        polygons.append([node_map[int(node_id)] for node_id in cell.node_indices])
    return polygons


def _mesh_triangulation_inputs(
    bundle: CatchmentMeshBundle,
) -> tuple[list[float], list[float], list[tuple[int, int, int]]]:
    node_index_map = {
        int(node.node_id): idx
        for idx, node in enumerate(bundle.nodes)
    }
    x_values = [float(node.x) for node in bundle.nodes]
    y_values = [float(node.y) for node in bundle.nodes]
    triangles: list[tuple[int, int, int]] = []
    for cell in bundle.cells:
        vertex_indices = [
            node_index_map[int(node_id)]
            for node_id in cell.node_indices
        ]
        if len(vertex_indices) < 3:
            continue
        anchor = vertex_indices[0]
        for idx in range(1, len(vertex_indices) - 1):
            triangles.append(
                (
                    int(anchor),
                    int(vertex_indices[idx]),
                    int(vertex_indices[idx + 1]),
                )
            )
    return x_values, y_values, triangles


def _node_topography_values(
    bundle: CatchmentMeshBundle,
) -> tuple[list[float], list[bool]]:
    values: list[float] = []
    valid_flags: list[bool] = []
    for node in bundle.nodes:
        if node.z_top is None:
            values.append(0.0)
            valid_flags.append(False)
            continue
        values.append(float(node.z_top))
        valid_flags.append(True)
    return values, valid_flags


def has_continuous_node_topography(bundle: CatchmentMeshBundle) -> bool:
    """Return True when the bundle can support a continuous nodal topography plot."""
    _, valid_flags = _node_topography_values(bundle)
    _, _, triangles = _mesh_triangulation_inputs(bundle)
    return any(
        bool(valid_flags[node_a] and valid_flags[node_b] and valid_flags[node_c])
        for node_a, node_b, node_c in triangles
    )


def _cell_numeric_values(bundle: CatchmentMeshBundle, color_by: str) -> list[float]:
    values: list[float] = []
    for cell in bundle.cells:
        raw_value = getattr(cell, color_by)
        if raw_value is None:
            values.append(float("nan"))
            continue
        values.append(float(raw_value))
    return values


def _cell_categorical_values(bundle: CatchmentMeshBundle, color_by: str) -> list[str]:
    values: list[str] = []
    for cell in bundle.cells:
        raw_value = getattr(cell, color_by)
        if raw_value is None or str(raw_value).strip() == "":
            values.append("unassigned")
            continue
        values.append(str(raw_value))
    return values


def _build_edge_segments(
    bundle: CatchmentMeshBundle,
    *,
    selector,
) -> list[list[tuple[float, float]]]:
    node_map = _node_xy_map(bundle)
    segments: list[list[tuple[float, float]]] = []
    for edge in bundle.edges:
        if not selector(edge):
            continue
        segments.append(
            [
                node_map[int(edge.node_a)],
                node_map[int(edge.node_b)],
            ]
        )
    return segments


def _style_axis(ax, *, node_map: Mapping[int, tuple[float, float]]) -> None:
    x_values = [coords[0] for coords in node_map.values()]
    y_values = [coords[1] for coords in node_map.values()]
    xmin = min(x_values)
    xmax = max(x_values)
    ymin = min(y_values)
    ymax = max(y_values)
    span_x = max(xmax - xmin, 1.0)
    span_y = max(ymax - ymin, 1.0)
    margin_x = 0.03 * span_x
    margin_y = 0.03 * span_y
    ax.set_xlim(xmin - margin_x, xmax + margin_x)
    ax.set_ylim(ymin - margin_y, ymax + margin_y)
    ax.set_aspect("equal")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")


def _build_info_text(bundle: CatchmentMeshBundle) -> str:
    metadata = dict(bundle.metadata)
    lines = [
        f"cells: {bundle.n_cells}",
        f"nodes: {bundle.n_nodes}",
        f"edges: {bundle.n_edges}",
    ]
    crs = metadata.get("crs")
    if crs is not None:
        lines.append(f"crs: {crs}")
    constraints_mode = metadata.get("constraints_mode")
    if constraints_mode is not None:
        lines.append(f"mode: {constraints_mode}")
    geology_available = bool(metadata.get("geology", {}).get("available", False))
    lines.append(f"geology: {'yes' if geology_available else 'no'}")
    return "\n".join(lines)


def _plot_numeric_cells(
    ax,
    *,
    polygons: list[list[tuple[float, float]]],
    values: list[float],
    cmap: str,
    edge_color: str,
    edge_linewidth: float,
    PolyCollection,
    plt,
) -> object:
    collection = PolyCollection(
        polygons,
        array=values,
        cmap=cmap,
        edgecolors=edge_color,
        linewidths=edge_linewidth,
    )
    ax.add_collection(collection)
    plt.colorbar(collection, ax=ax, fraction=0.04, pad=0.02)
    return collection


def _plot_categorical_cells(
    ax,
    *,
    polygons: list[list[tuple[float, float]]],
    raw_values: list[str],
    cmap_name: str,
    edge_color: str,
    edge_linewidth: float,
    matplotlib,
    PolyCollection,
    Patch,
) -> list[object]:
    categories = sorted(set(raw_values))
    cmap = matplotlib.colormaps.get_cmap(cmap_name).resampled(max(1, len(categories)))
    color_lookup = {
        category: cmap(idx)
        for idx, category in enumerate(categories)
    }
    facecolors = [color_lookup[value] for value in raw_values]
    collection = PolyCollection(
        polygons,
        facecolors=facecolors,
        edgecolors=edge_color,
        linewidths=edge_linewidth,
    )
    ax.add_collection(collection)
    return [
        Patch(facecolor=color_lookup[category], edgecolor="0.35", label=category)
        for category in categories
    ]


def _draw_overlay_edges(
    ax,
    *,
    bundle: CatchmentMeshBundle,
    plot_cfg: MeshBundlePlotConfig,
    LineCollection,
) -> None:
    line_handles: list[tuple[str, str]] = []
    if plot_cfg.show_boundary_edges:
        boundary_segments = _build_edge_segments(
            bundle,
            selector=lambda edge: str(edge.edge_kind) == "boundary",
        )
        if boundary_segments:
            ax.add_collection(
                LineCollection(boundary_segments, colors="black", linewidths=1.0)
            )
            line_handles.append(("Boundary", "black"))

    if plot_cfg.show_geology_interfaces:
        interface_segments = _build_edge_segments(
            bundle,
            selector=lambda edge: str(edge.edge_kind) == "geology_interface",
        )
        if interface_segments:
            ax.add_collection(
                LineCollection(interface_segments, colors="#c85a00", linewidths=1.2)
            )
            line_handles.append(("Geology interface", "#c85a00"))

    if plot_cfg.show_river_edges:
        river_segments = _build_edge_segments(
            bundle,
            selector=lambda edge: bool(edge.is_river),
        )
        if river_segments:
            ax.add_collection(
                LineCollection(river_segments, colors="#1f78b4", linewidths=1.1)
            )
            line_handles.append(("River edge", "#1f78b4"))

    if line_handles:
        from matplotlib.lines import Line2D

        ax.add_artist(
            ax.legend(
                handles=[
                    Line2D([0], [0], color=color, lw=1.1, label=label)
                    for label, color in line_handles
                ],
                loc="lower left",
                fontsize=9,
                framealpha=0.95,
                title="Overlays",
                title_fontsize=10,
            )
        )


def _draw_mesh_bundle_panel(
    ax,
    *,
    bundle: CatchmentMeshBundle,
    plot_cfg: MeshBundlePlotConfig,
    color_by: str,
    cmap: str,
    title: str,
    show_info_box: bool,
    matplotlib,
    plt,
    LineCollection,
    PolyCollection,
    Patch,
) -> None:
    mesh_edge_color = str(plot_cfg.mesh_edge_color) if plot_cfg.show_mesh_edges else "none"
    mesh_edge_linewidth = (
        float(plot_cfg.mesh_edge_linewidth) if plot_cfg.show_mesh_edges else 0.0
    )
    polygons = _cell_polygons(bundle)
    if color_by in NUMERIC_COLOR_FIELDS:
        values = _cell_numeric_values(bundle, color_by)
        _plot_numeric_cells(
            ax,
            polygons=polygons,
            values=values,
            cmap=cmap,
            edge_color=mesh_edge_color,
            edge_linewidth=mesh_edge_linewidth,
            PolyCollection=PolyCollection,
            plt=plt,
        )
    else:
        legend_handles = _plot_categorical_cells(
            ax,
            polygons=polygons,
            raw_values=_cell_categorical_values(bundle, color_by),
            cmap_name=cmap,
            edge_color=mesh_edge_color,
            edge_linewidth=mesh_edge_linewidth,
            matplotlib=matplotlib,
            PolyCollection=PolyCollection,
            Patch=Patch,
        )
        if legend_handles:
            ax.legend(
                handles=legend_handles,
                title=str(color_by),
                loc="upper left",
                fontsize=9,
                title_fontsize=10,
                framealpha=0.95,
            )

    _draw_overlay_edges(
        ax,
        bundle=bundle,
        plot_cfg=plot_cfg,
        LineCollection=LineCollection,
    )

    if plot_cfg.annotate_cell_ids:
        for cell in bundle.cells:
            ax.text(
                float(cell.centroid_x),
                float(cell.centroid_y),
                str(cell.cell_id),
                ha="center",
                va="center",
                fontsize=7,
                color="0.15",
            )

    node_map = _node_xy_map(bundle)
    _style_axis(ax, node_map=node_map)
    ax.set_title(title)
    if show_info_box:
        ax.text(
            0.99,
            0.01,
            _build_info_text(bundle),
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


def _draw_continuous_topography_panel(
    ax,
    *,
    bundle: CatchmentMeshBundle,
    plot_cfg: MeshBundlePlotConfig,
    cmap: str,
    title: str,
    plt,
    LineCollection,
) -> bool:
    from matplotlib import tri as mtri

    x_values, y_values, triangles = _mesh_triangulation_inputs(bundle)
    if not triangles:
        return False

    z_values, valid_flags = _node_topography_values(bundle)
    triangle_mask = [
        not bool(valid_flags[node_a] and valid_flags[node_b] and valid_flags[node_c])
        for node_a, node_b, node_c in triangles
    ]
    if all(triangle_mask):
        return False

    triangulation = mtri.Triangulation(x_values, y_values, triangles)
    if any(triangle_mask):
        triangulation.set_mask(triangle_mask)

    surface = ax.tripcolor(
        triangulation,
        z_values,
        cmap=cmap,
        shading="gouraud",
    )
    plt.colorbar(surface, ax=ax, fraction=0.04, pad=0.02)

    if plot_cfg.show_mesh_edges:
        ax.triplot(
            triangulation,
            color=str(plot_cfg.mesh_edge_color),
            linewidth=float(plot_cfg.mesh_edge_linewidth),
        )

    _draw_overlay_edges(
        ax,
        bundle=bundle,
        plot_cfg=plot_cfg,
        LineCollection=LineCollection,
    )

    if plot_cfg.annotate_cell_ids:
        for cell in bundle.cells:
            ax.text(
                float(cell.centroid_x),
                float(cell.centroid_y),
                str(cell.cell_id),
                ha="center",
                va="center",
                fontsize=7,
                color="0.15",
            )

    node_map = _node_xy_map(bundle)
    _style_axis(ax, node_map=node_map)
    ax.set_title(title)
    return True


def build_mesh_bundle_figure(
    bundle: CatchmentMeshBundle,
    *,
    config: MeshBundleViewerConfig,
):
    """Build one overview figure for the selected bundle."""
    matplotlib, plt, LineCollection, PolyCollection, _, Patch = _load_matplotlib(
        show_plot=config.show_plot
    )
    panel_count = 2 if config.plot.show_topography_panel else 1
    fig, axes = plt.subplots(
        1,
        panel_count,
        figsize=config.plot.figsize,
        dpi=config.plot.dpi,
    )
    if panel_count == 1:
        axes = [axes]
    else:
        axes = list(axes)

    left_title = config.plot.title
    if left_title is None:
        left_title = (
            f"Catchment mesh bundle overview\n"
            f"color_by = {config.plot.color_by}"
        )
    _draw_mesh_bundle_panel(
        axes[0],
        bundle=bundle,
        plot_cfg=config.plot,
        color_by=config.plot.color_by,
        cmap=config.plot.cmap,
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
            right_title = (
                f"Topography-style view\n"
                f"color_by = {config.plot.topography_color_by}"
            )
        rendered = _draw_continuous_topography_panel(
            axes[1],
            bundle=bundle,
            plot_cfg=config.plot,
            cmap=config.plot.topography_cmap,
            title=right_title,
            plt=plt,
            LineCollection=LineCollection,
        )
        if not rendered:
            fallback_title = f"{right_title}\ncell fallback"
            _draw_mesh_bundle_panel(
                axes[1],
                bundle=bundle,
                plot_cfg=config.plot,
                color_by=config.plot.topography_color_by,
                cmap=config.plot.topography_cmap,
                title=fallback_title,
                show_info_box=False,
                matplotlib=matplotlib,
                plt=plt,
                LineCollection=LineCollection,
                PolyCollection=PolyCollection,
                Patch=Patch,
            )

    fig.tight_layout()
    return fig


__all__ = [
    "build_mesh_bundle_figure",
    "has_continuous_node_topography",
]
