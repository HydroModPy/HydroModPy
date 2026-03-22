"""Plotting helpers for the reference 2D zone-conformal case."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import rasterio
from rasterio.enums import Resampling

from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.contracts import (
    ZoneConformalMeshingInputs,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.planning import (
    _iter_river_lines,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.scope_resolution import (
    _valid_geometry_mask,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_base.run_case_gmsh import (
    _disable_axis_offset,
    _show_figures_blocking,
)


def _build_zone_color_map(zone_keys: list[str]):
    cmap = plt.get_cmap("tab20", max(2, len(zone_keys)))
    key_to_idx = {zone_key: idx for idx, zone_key in enumerate(zone_keys)}
    key_to_color = {
        zone_key: cmap(float(idx) / max(float(len(zone_keys) - 1), 1.0))
        for zone_key, idx in key_to_idx.items()
    }
    return key_to_idx, key_to_color


def _draw_mesh_edges(
    ax, mesh, *, color: str = "0.20", lw: float = 0.28, alpha: float = 0.65
) -> None:
    for cell in mesh.cells:
        vertices = np.asarray(cell.vertices, dtype=float)
        closed = np.vstack((vertices, vertices[0]))
        ax.plot(closed[:, 0], closed[:, 1], color=color, lw=lw, alpha=alpha)


def _draw_domain_outline(ax, domain_gdf: gpd.GeoDataFrame) -> None:
    domain_gdf.boundary.plot(
        ax=ax, color="black", linewidth=1.2, linestyle="--", zorder=6
    )


def _resolve_river_lines_for_plot(
    *,
    river_trace: object | None,
    domain_geographic: object | None,
) -> list[object]:
    lines = _iter_river_lines(river_trace)
    _ = domain_geographic
    return lines


def _draw_river_lines(
    ax,
    *,
    river_lines: list[object],
    color: str = "#1f78b4",
    lw: float = 1.05,
    alpha: float = 0.9,
) -> int:
    for line in river_lines:
        x_vals, y_vals = line.xy
        ax.plot(x_vals, y_vals, color=color, lw=lw, alpha=alpha, zorder=7)
    return int(len(river_lines))


def _load_catchment_outline(
    domain_geographic: object | None,
) -> gpd.GeoDataFrame | None:
    if domain_geographic is None:
        return None
    watershed_shp = getattr(domain_geographic, "watershed_shp", None)
    if watershed_shp is None:
        return None
    try:
        gdf = gpd.read_file(str(watershed_shp))
    except Exception:
        return None
    if gdf.empty:
        return None
    gdf = gdf[_valid_geometry_mask(gdf.geometry)].copy()
    if gdf.empty:
        return None
    return gdf


def _load_topography_background(
    domain_geographic: object | None,
) -> tuple[np.ndarray, tuple[float, float, float, float]] | None:
    if domain_geographic is None:
        return None
    dem_path = getattr(domain_geographic, "watershed_box_buff_dem", None)
    if dem_path is None:
        return None
    try:
        with rasterio.open(str(dem_path)) as src:
            dem = src.read(1)
            nodata = src.nodata
            if nodata is not None:
                dem = np.where(dem == nodata, np.nan, dem)
            extent = (
                float(src.bounds.left),
                float(src.bounds.right),
                float(src.bounds.bottom),
                float(src.bounds.top),
            )
    except Exception:
        return None
    return np.asarray(dem, dtype=float), extent


def _load_regional_topography_background(
    domain_geographic: object | None,
) -> tuple[np.ndarray, tuple[float, float, float, float]] | None:
    if domain_geographic is None:
        return None
    dem_path = getattr(domain_geographic, "regional_dem_path", None)
    if dem_path is None:
        return None
    try:
        with rasterio.open(str(dem_path)) as src:
            max_dim = 1400
            scale = max(
                float(src.width) / float(max_dim),
                float(src.height) / float(max_dim),
                1.0,
            )
            out_height = max(1, int(round(float(src.height) / scale)))
            out_width = max(1, int(round(float(src.width) / scale)))
            dem = src.read(
                1,
                out_shape=(out_height, out_width),
                resampling=Resampling.bilinear,
            )
            nodata = src.nodata
            if nodata is not None:
                dem = np.where(dem == nodata, np.nan, dem)
            extent = (
                float(src.bounds.left),
                float(src.bounds.right),
                float(src.bounds.bottom),
                float(src.bounds.top),
            )
    except Exception:
        return None
    return np.asarray(dem, dtype=float), extent


def _set_panel_limits(
    ax,
    *,
    bounds: list[float],
) -> None:
    xmin, ymin, xmax, ymax = [float(v) for v in bounds]
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)


def _build_geographic_mesh_figure(
    *,
    domain_gdf: gpd.GeoDataFrame,
    partition_gdf: gpd.GeoDataFrame,
    mesh,
    domain_bounds: list[float],
    catchment_gdf: gpd.GeoDataFrame | None,
    topo_background: tuple[np.ndarray, tuple[float, float, float, float]] | None,
    river_lines: list[object],
):
    zone_keys = sorted(
        str(zone_key)
        for zone_key in partition_gdf["zone_key"].astype(str).unique().tolist()
    )
    key_to_idx, key_to_color = _build_zone_color_map(zone_keys)

    fig, axes = plt.subplots(1, 2, figsize=(18.5, 9.5), dpi=160)
    ax_topo, ax_overlay = axes

    if topo_background is not None:
        dem, extent = topo_background
        im = ax_topo.imshow(
            dem,
            extent=extent,
            cmap="terrain",
            origin="upper",
            zorder=1,
        )
        cbar = fig.colorbar(im, ax=ax_topo, fraction=0.042, pad=0.015)
        cbar.set_label("Elevation [m]", fontsize=11)
        cbar.ax.tick_params(labelsize=9)
    else:
        ax_topo.set_facecolor("0.96")

    if catchment_gdf is not None:
        catchment_gdf.boundary.plot(
            ax=ax_topo,
            color="black",
            linewidth=1.25,
            zorder=8,
        )
        catchment_gdf.boundary.plot(
            ax=ax_overlay,
            color="black",
            linewidth=1.25,
            zorder=8,
        )

    _draw_domain_outline(ax_topo, domain_gdf)
    _draw_domain_outline(ax_overlay, domain_gdf)
    river_count = _draw_river_lines(ax_topo, river_lines=river_lines)
    _plot_zone_panel(
        ax_overlay,
        gdf=partition_gdf,
        key_to_idx=key_to_idx,
        title="Geology + conformal mesh + hydro network",
    )
    _draw_mesh_edges(ax_overlay, mesh)
    _draw_river_lines(ax_overlay, river_lines=river_lines)
    _draw_domain_outline(ax_overlay, domain_gdf)
    if catchment_gdf is not None:
        catchment_gdf.boundary.plot(
            ax=ax_overlay,
            color="black",
            linewidth=1.15,
            zorder=8,
        )

    _set_panel_limits(ax_topo, bounds=domain_bounds)
    _set_panel_limits(ax_overlay, bounds=domain_bounds)

    ax_topo.set_title("Topography + catchment limits + hydro network", fontsize=15)
    for ax in (ax_topo, ax_overlay):
        ax.set_xlabel("x [m]", fontsize=12)
        ax.set_ylabel("y [m]", fontsize=12)
        ax.tick_params(labelsize=10)
        ax.set_aspect("equal")
        _disable_axis_offset(ax)

    legend_handles: list[Line2D] = []
    if catchment_gdf is not None:
        legend_handles.append(
            Line2D([0], [0], color="black", lw=1.25, label="Catchment boundary")
        )
    legend_handles.append(
        Line2D([0], [0], color="black", lw=1.2, linestyle="--", label="Meshing domain")
    )
    if river_count > 0:
        legend_handles.append(
            Line2D([0], [0], color="#1f78b4", lw=1.1, label="Hydro network")
        )
    legend_handles.append(
        Line2D([0], [0], color="0.20", lw=0.9, label="Mesh edges")
    )
    overlay_legend = ax_overlay.legend(
        handles=legend_handles,
        loc="lower left",
        fontsize=10,
        framealpha=0.92,
    )
    ax_overlay.add_artist(overlay_legend)

    geology_handles = [
        Patch(facecolor=key_to_color[zone_key], edgecolor="0.25", label=zone_key)
        for zone_key in zone_keys
    ]
    if geology_handles:
        ax_overlay.legend(
            handles=geology_handles,
            title="Constrained zones",
            loc="upper left",
            fontsize=9,
            title_fontsize=10,
            framealpha=0.92,
        )

    fig.suptitle("Mesh-catchment overview", fontsize=18)
    fig.subplots_adjust(
        left=0.05, right=0.985, top=0.92, bottom=0.08, wspace=0.12
    )
    return fig


def _build_regional_context_figure(
    *,
    domain_gdf: gpd.GeoDataFrame,
    catchment_gdf: gpd.GeoDataFrame | None,
    topo_background: tuple[np.ndarray, tuple[float, float, float, float]] | None,
    river_lines: list[object],
    outlet_xy: tuple[float, float] | None,
):
    fig, ax = plt.subplots(1, 1, figsize=(11.5, 9.5), dpi=160)

    extent = None
    if topo_background is not None:
        dem, extent = topo_background
        im = ax.imshow(
            dem,
            extent=extent,
            cmap="terrain",
            origin="upper",
            zorder=1,
        )
        cbar = fig.colorbar(im, ax=ax, fraction=0.040, pad=0.018)
        cbar.set_label("Elevation [m]", fontsize=11)
        cbar.ax.tick_params(labelsize=9)
    else:
        ax.set_facecolor("0.96")

    river_count = _draw_river_lines(ax, river_lines=river_lines)
    if catchment_gdf is not None:
        catchment_gdf.boundary.plot(
            ax=ax,
            color="black",
            linewidth=1.4,
            zorder=8,
        )
    _draw_domain_outline(ax, domain_gdf)

    if outlet_xy is not None:
        ax.scatter(
            [float(outlet_xy[0])],
            [float(outlet_xy[1])],
            marker="o",
            s=28,
            facecolor="#ef8a00",
            edgecolor="black",
            linewidth=0.6,
            zorder=9,
        )

    if extent is not None:
        ax.set_xlim(extent[0], extent[1])
        ax.set_ylim(extent[2], extent[3])
    else:
        reference_gdf = catchment_gdf if catchment_gdf is not None else domain_gdf
        xmin, ymin, xmax, ymax = [float(v) for v in reference_gdf.total_bounds]
        span_x = max(xmax - xmin, 1.0)
        span_y = max(ymax - ymin, 1.0)
        pad_x = 0.08 * span_x
        pad_y = 0.08 * span_y
        ax.set_xlim(xmin - pad_x, xmax + pad_x)
        ax.set_ylim(ymin - pad_y, ymax + pad_y)

    ax.set_title("Regional catchment location on DEM", fontsize=16)
    ax.set_xlabel("x [m]", fontsize=12)
    ax.set_ylabel("y [m]", fontsize=12)
    ax.tick_params(labelsize=10)
    ax.set_aspect("equal")
    _disable_axis_offset(ax)

    legend_handles: list[Line2D] = [
        Line2D([0], [0], color="black", lw=1.3, label="Catchment boundary"),
        Line2D([0], [0], color="black", lw=1.2, linestyle="--", label="Meshing domain"),
    ]
    if river_count > 0:
        legend_handles.append(
            Line2D([0], [0], color="#1f78b4", lw=1.1, label="Hydro network")
        )
    if outlet_xy is not None:
        legend_handles.append(
            Line2D(
                [0],
                [0],
                marker="o",
                color="black",
                markerfacecolor="#ef8a00",
                markersize=6,
                linewidth=0.0,
                label="Outlet",
            )
        )
    ax.legend(handles=legend_handles, loc="lower left", fontsize=10, framealpha=0.92)
    fig.subplots_adjust(left=0.08, right=0.96, top=0.93, bottom=0.08)
    return fig


def _plot_zone_panel(
    ax, *, gdf: gpd.GeoDataFrame, key_to_idx: Mapping[str, int], title: str
) -> None:
    plot_gdf = gdf.copy()
    plot_gdf["zone_idx"] = plot_gdf["zone_key"].map(key_to_idx).astype(float)
    cmap = plt.get_cmap("tab20", max(2, len(key_to_idx)))
    plot_gdf.plot(
        column="zone_idx",
        ax=ax,
        cmap=cmap,
        linewidth=0.35,
        edgecolor="0.30",
        legend=False,
    )
    ax.set_title(title, fontsize=16)
    ax.set_xlabel("x [m]", fontsize=13)
    ax.set_ylabel("y [m]", fontsize=13)
    ax.tick_params(labelsize=11)
    ax.set_aspect("equal")
    _disable_axis_offset(ax)


def _draw_legend_panel(
    ax,
    *,
    key_to_color: Mapping[str, Any],
    n_source_features: int,
    n_partition_faces: int,
    domain_area: float,
    domain_kind: str,
    interface_refinement: Mapping[str, Any],
) -> None:
    ax.axis("off")
    zone_keys = list(sorted(key_to_color))
    handles = [
        Patch(facecolor=key_to_color[zone_key], edgecolor="0.25", label=zone_key)
        for zone_key in zone_keys
    ]
    legend = ax.legend(
        handles=handles,
        title="Constrained zones",
        loc="upper left",
        ncol=4,
        fontsize=11,
        title_fontsize=13,
        frameon=True,
    )
    legend.get_frame().set_alpha(0.95)
    refinement_enabled = bool(interface_refinement.get("enabled", False))
    interface_size = interface_refinement.get("interface_size")
    interface_distance = interface_refinement.get("interface_distance")
    refinement_label = "off"
    if refinement_enabled:
        refinement_label = (
            f"on (size={float(interface_size):.3g}, dist={float(interface_distance):.3g})"
            if (interface_size is not None and interface_distance is not None)
            else "on"
        )
    ax.text(
        0.01,
        0.05,
        (
            f"Clipped source features: {n_source_features}    "
            f"Partition faces: {n_partition_faces}    "
            f"Domain area: {float(domain_area):.3g} m2    "
            f"Domain kind: {domain_kind}    "
            f"Interface refinement: {refinement_label}    "
            f"Dashed black outline = effective meshing domain"
        ),
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=12,
        color="0.15",
    )


def _build_figure(
    *,
    clipped_gdf: gpd.GeoDataFrame,
    partition_gdf: gpd.GeoDataFrame,
    domain_gdf: gpd.GeoDataFrame,
    mesh,
    domain_bounds: list[float],
    domain_area: float,
    domain_kind: str,
    interface_refinement: Mapping[str, Any],
    domain_geographic: object | None = None,
    river_trace: object | None = None,
):
    catchment_gdf = _load_catchment_outline(domain_geographic)
    topo_background = _load_topography_background(domain_geographic)
    river_lines = _resolve_river_lines_for_plot(
        river_trace=river_trace,
        domain_geographic=domain_geographic,
    )
    if catchment_gdf is not None or topo_background is not None or river_lines:
        return _build_geographic_mesh_figure(
            domain_gdf=domain_gdf,
            partition_gdf=partition_gdf,
            mesh=mesh,
            domain_bounds=domain_bounds,
            catchment_gdf=catchment_gdf,
            topo_background=topo_background,
            river_lines=river_lines,
        )

    zone_keys = sorted(
        str(zone_key)
        for zone_key in partition_gdf["zone_key"].astype(str).unique().tolist()
    )
    key_to_idx, key_to_color = _build_zone_color_map(zone_keys)

    fig = plt.figure(figsize=(18.0, 10.5), dpi=160)
    axes = fig.subplot_mosaic(
        [["source", "mesh"], ["legend", "legend"]],
        height_ratios=[1.0, 0.28],
    )
    ax_source = axes["source"]
    ax_mesh = axes["mesh"]
    ax_legend = axes["legend"]

    _plot_zone_panel(
        ax_source,
        gdf=clipped_gdf,
        key_to_idx=key_to_idx,
        title="Constrained source polygons",
    )
    _plot_zone_panel(
        ax_mesh,
        gdf=partition_gdf,
        key_to_idx=key_to_idx,
        title="Zone-conformal partition with generated mesh overlay",
    )
    _draw_domain_outline(ax_source, domain_gdf)
    _draw_domain_outline(ax_mesh, domain_gdf)
    _draw_mesh_edges(ax_mesh, mesh)

    xmin, ymin, xmax, ymax = [float(v) for v in domain_bounds]
    for ax in (ax_source, ax_mesh):
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)

    _draw_legend_panel(
        ax_legend,
        key_to_color=key_to_color,
        n_source_features=int(len(clipped_gdf)),
        n_partition_faces=int(len(partition_gdf)),
        domain_area=float(domain_area),
        domain_kind=domain_kind,
        interface_refinement=interface_refinement,
    )
    fig.suptitle("Reference 2D zone-conformal Gmsh mesh", fontsize=19)
    fig.subplots_adjust(
        left=0.05, right=0.985, top=0.92, bottom=0.06, wspace=0.12, hspace=0.12
    )
    return fig


def _resolve_outlet_xy(domain_geographic: object | None) -> tuple[float, float] | None:
    if domain_geographic is None:
        return None
    x_outlet = getattr(domain_geographic, "x_outlet", None)
    y_outlet = getattr(domain_geographic, "y_outlet", None)
    if x_outlet is None or y_outlet is None:
        return None
    return float(x_outlet), float(y_outlet)


def _write_optional_figure_artifacts(
    *,
    figure_path: Path | None,
    figure_regional_path: Path | None,
    show_plot: bool,
    result,
    meshing_inputs: ZoneConformalMeshingInputs,
    partition_gdf: gpd.GeoDataFrame,
    domain_geographic: object | None,
) -> dict[str, str]:
    if figure_path is None and figure_regional_path is None and not show_plot:
        return {}

    common_plot_kwargs = {
        "clipped_gdf": meshing_inputs.zone_gdf,
        "partition_gdf": partition_gdf,
        "domain_gdf": meshing_inputs.domain_payload.gdf,
        "mesh": result.mesh,
        "domain_bounds": list(meshing_inputs.domain_payload.geometry.bounds),
        "domain_area": float(meshing_inputs.domain_payload.summary["domain_area"]),
        "domain_kind": str(meshing_inputs.domain_payload.summary["domain_kind"]),
        "interface_refinement": dict(
            result.summary.get("mesh_size_fields", {}).get("interface_refinement", {})
        ),
        "domain_geographic": domain_geographic,
        "river_trace": meshing_inputs.resolved_river_trace,
    }

    fig = None
    regional_fig = None
    updates: dict[str, str] = {}
    try:
        if figure_path is not None or show_plot:
            fig = _build_figure(**common_plot_kwargs)

        if figure_regional_path is not None or show_plot:
            regional_fig = _build_regional_context_figure(
                domain_gdf=meshing_inputs.domain_payload.gdf,
                catchment_gdf=_load_catchment_outline(domain_geographic),
                topo_background=_load_regional_topography_background(domain_geographic),
                river_lines=_resolve_river_lines_for_plot(
                    river_trace=meshing_inputs.resolved_river_trace,
                    domain_geographic=domain_geographic,
                ),
                outlet_xy=_resolve_outlet_xy(domain_geographic),
            )

        if figure_path is not None and fig is not None:
            fig.savefig(figure_path)
            updates["output_figure"] = str(figure_path)
        if figure_regional_path is not None and regional_fig is not None:
            regional_fig.savefig(figure_regional_path)
            updates["output_figure_regional"] = str(figure_regional_path)

        if show_plot:
            _show_figures_blocking(fig, regional_fig)
    finally:
        if not show_plot:
            if fig is not None:
                plt.close(fig)
            if regional_fig is not None:
                plt.close(regional_fig)

    return updates


__all__ = [
    "_build_figure",
    "_build_geographic_mesh_figure",
    "_build_regional_context_figure",
    "_build_zone_color_map",
    "_draw_domain_outline",
    "_draw_legend_panel",
    "_draw_mesh_edges",
    "_draw_river_lines",
    "_load_catchment_outline",
    "_load_regional_topography_background",
    "_load_topography_background",
    "_plot_zone_panel",
    "_resolve_river_lines_for_plot",
    "_write_optional_figure_artifacts",
    "_set_panel_limits",
]
