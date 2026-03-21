"""Run the reference 2D zone-conformal meshing case.

This script is the pedagogical entry point for the zone-conformal workflow.
It builds one planar mesh constrained by configurable inputs (geology zones,
river traces, or both), exports inspection artifacts, and keeps the focus on
geometry and visual QA before any 3D extrusion or solver coupling is
introduced.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling

from hydromodpy.solver.utils.mesh.gmsh_grid import (
    generate_zone_conformal_mesh_from_dataframe,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.case_config import (
    _resolve_case_config,
    _resolve_constraints_mode,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.contracts import (
    ZoneConformalMeshingInputs,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.planning import (
    _build_zone_conformal_meshing_inputs,
    _clip_river_trace_to_domain,
    _iter_river_lines,
    _resolve_river_trace_for_meshing,
    _valid_geometry_mask,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.reporting import (
    _build_constraints_qa_contract,
    _build_summary,
    _write_json,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_base.run_case_gmsh import (
    _disable_axis_offset,
    _show_figures_blocking,
)

DEFAULT_CONFIG_FILE = "case_config_zone_conformal.toml"
DEFAULT_SECTION = "mesh_case"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate one conformal 2D Gmsh mesh from configurable zone and river constraints."
    )
    parser.add_argument("--config-file", default=DEFAULT_CONFIG_FILE)
    parser.add_argument("--section", default=DEFAULT_SECTION)
    parser.add_argument("--output-mesh", default=None)
    parser.add_argument("--output-summary-json", default=None)
    parser.add_argument("--output-figure", default=None)
    parser.add_argument("--output-figure-regional", default=None)
    parser.add_argument("--show-plot", action="store_true")
    return parser.parse_args(argv)


def _resolve_config_path(raw_config: str | Path) -> Path:
    candidate = Path(raw_config).expanduser()
    if candidate.is_absolute() and candidate.exists():
        return candidate.resolve()
    cwd_candidate = candidate.resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    script_candidate = (Path(__file__).resolve().parent / candidate).resolve()
    if script_candidate.exists():
        return script_candidate
    raise FileNotFoundError(f"Config TOML not found: '{raw_config}'")



def _resolve_optional_output_path(
    config_toml: Path,
    config_value: Any,
    override_value: str | None,
) -> Path | None:
    raw = override_value if override_value is not None else config_value
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "":
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (config_toml.parent / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _build_partition_gdf(partition, *, crs) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "face_id": [int(face.face_id) for face in partition.faces],
            "zone_key": [str(face.zone_key) for face in partition.faces],
            "face_area": [float(face.area) for face in partition.faces],
        },
        geometry=[face.polygon for face in partition.faces],
        crs=crs,
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
    if (
        catchment_gdf is not None
        or topo_background is not None
        or river_lines
    ):
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


def run_reference_2d_zone_conformal_case_from_toml(
    config_toml: str | Path,
    *,
    section: str = DEFAULT_SECTION,
    section_data_override: Mapping[str, Any] | None = None,
    output_mesh: str | Path | None = None,
    output_summary_json: str | Path | None = None,
    output_figure: str | Path | None = None,
    output_figure_regional: str | Path | None = None,
    river_trace: object | None = None,
    domain_geographic: object | None = None,
    show_plot: bool = False,
) -> dict[str, Any]:
    config_path = _resolve_config_path(config_toml)
    cfg = _resolve_case_config(
        config_path,
        section=section,
        section_data_override=section_data_override,
    )
    meshing_inputs = _build_zone_conformal_meshing_inputs(
        cfg=cfg,
        config_path=config_path,
        river_trace=river_trace,
        domain_geographic=domain_geographic,
    )
    constraints_mode = str(meshing_inputs.usage.constraints_mode)

    mesh_path = _resolve_optional_output_path(
        config_path,
        cfg.get("output_mesh"),
        None if output_mesh is None else str(output_mesh),
    )
    summary_path = _resolve_optional_output_path(
        config_path,
        cfg.get("output_summary_json"),
        None if output_summary_json is None else str(output_summary_json),
    )
    figure_path = _resolve_optional_output_path(
        config_path,
        cfg.get("output_figure"),
        None if output_figure is None else str(output_figure),
    )
    figure_regional_path = _resolve_optional_output_path(
        config_path,
        cfg.get("output_figure_regional"),
        None if output_figure_regional is None else str(output_figure_regional),
    )

    if mesh_path is None:
        raise ValueError(
            "An output mesh path is required for the conformal reference case"
        )

    result = generate_zone_conformal_mesh_from_dataframe(
        meshing_inputs.zone_gdf,
        output_path=mesh_path,
        zone_key_column="zone_key",
        domain_geometry=meshing_inputs.domain_payload["geometry"],
        algorithm=str(meshing_inputs.zone_meshing_cfg["algorithm"]),
        global_size=float(meshing_inputs.zone_meshing_cfg["global_size"]),
        min_size=meshing_inputs.zone_meshing_cfg["min_size"],
        max_size=meshing_inputs.zone_meshing_cfg["max_size"],
        simplify_tolerance=float(meshing_inputs.zone_meshing_cfg["simplify_tolerance"]),
        heal_tolerance=float(meshing_inputs.zone_meshing_cfg["heal_tolerance"]),
        min_polygon_area=float(meshing_inputs.zone_meshing_cfg["min_polygon_area"]),
        refine_interfaces=bool(meshing_inputs.zone_meshing_cfg["refine_interfaces"]),
        interface_size=meshing_inputs.zone_meshing_cfg["interface_size"],
        interface_distance=meshing_inputs.zone_meshing_cfg["interface_distance"],
        interface_sampling=int(meshing_inputs.zone_meshing_cfg["interface_sampling"]),
        linear_constraints=meshing_inputs.linear_constraints,
        refinement_scope_geometry=(
            meshing_inputs.refinement_scope_payload["geometry"]
            if meshing_inputs.refinement_scope_is_custom
            else None
        ),
        model_name=f"reference_2d_zone_conformal_{constraints_mode}",
    )

    partition_gdf = _build_partition_gdf(result.partition, crs=meshing_inputs.zone_gdf.crs)
    summary = _build_summary(
        result=result,
        source_payload=meshing_inputs.source_payload,
        clipped_gdf=meshing_inputs.zone_gdf,
        domain_payload=meshing_inputs.domain_payload,
    )
    summary["constraints_mode"] = constraints_mode
    summary["interface_scope"] = dict(meshing_inputs.interface_scope_payload["summary"])
    summary["refinement_scope"] = dict(meshing_inputs.refinement_scope_payload["summary"])
    summary["constraints_qa"] = _build_constraints_qa_contract(
        summary=summary,
        constraints_mode=constraints_mode,
        refine_interfaces=bool(meshing_inputs.zone_meshing_cfg["refine_interfaces"]),
    )
    qa_checks = (
        dict(summary.get("qa_checks", {}))
        if isinstance(summary.get("qa_checks"), Mapping)
        else {}
    )
    qa_checks["constraints_contract_pass"] = bool(
        summary["constraints_qa"]["overall_pass"]
    )
    summary["qa_checks"] = qa_checks
    if meshing_inputs.usage.uses_river_constraints and meshing_inputs.rivers_cfg is not None:
        summary["rivers_config"] = {
            "source": str(meshing_inputs.rivers_cfg["source"]),
            "path": meshing_inputs.rivers_cfg["path"],
            "clip_to_domain": bool(meshing_inputs.rivers_cfg["clip_to_domain"]),
            "min_segment_length": float(meshing_inputs.rivers_cfg["min_segment_length"]),
            "snap_tolerance": float(meshing_inputs.rivers_cfg["snap_tolerance"]),
        }
    if meshing_inputs.watershed_boundary_cfg is not None:
        summary["watershed_boundary_config"] = {
            "enabled": bool(meshing_inputs.watershed_boundary_cfg["enabled"]),
            "source": str(meshing_inputs.watershed_boundary_cfg["source"]),
            "clip_to_domain": bool(
                meshing_inputs.watershed_boundary_cfg["clip_to_domain"]
            ),
            "min_segment_length": float(
                meshing_inputs.watershed_boundary_cfg["min_segment_length"]
            ),
            "participates_in_refinement": bool(
                meshing_inputs.watershed_boundary_cfg["participates_in_refinement"]
            ),
            "smoothing": {
                "enabled": bool(
                    meshing_inputs.watershed_boundary_cfg["smoothing"]["enabled"]
                ),
                "simplify_tolerance": float(
                    meshing_inputs.watershed_boundary_cfg["smoothing"][
                        "simplify_tolerance"
                    ]
                ),
                "heal_tolerance": float(
                    meshing_inputs.watershed_boundary_cfg["smoothing"][
                        "heal_tolerance"
                    ]
                ),
                "min_polygon_area": float(
                    meshing_inputs.watershed_boundary_cfg["smoothing"][
                        "min_polygon_area"
                    ]
                ),
            },
        }
        linear_constraints_summary = summary.get("linear_constraints", {})
        if isinstance(linear_constraints_summary, Mapping):
            summary["watershed_boundary"] = dict(
                linear_constraints_summary.get("watershed::boundary", {})
            )
    summary["output_mesh"] = str(mesh_path)

    if figure_path is not None or figure_regional_path is not None or show_plot:
        common_plot_kwargs = {
            "clipped_gdf": meshing_inputs.zone_gdf,
            "partition_gdf": partition_gdf,
            "domain_gdf": meshing_inputs.domain_payload["gdf"],
            "mesh": result.mesh,
            "domain_bounds": list(meshing_inputs.domain_payload["geometry"].bounds),
            "domain_area": float(meshing_inputs.domain_payload["summary"]["domain_area"]),
            "domain_kind": str(meshing_inputs.domain_payload["summary"]["domain_kind"]),
            "interface_refinement": dict(
                result.summary.get("mesh_size_fields", {}).get(
                    "interface_refinement", {}
                )
            ),
            "domain_geographic": domain_geographic,
            "river_trace": meshing_inputs.resolved_river_trace,
        }

        fig = None
        if figure_path is not None or show_plot:
            fig = _build_figure(**common_plot_kwargs)
        regional_fig = None
        if figure_regional_path is not None or show_plot:
            catchment_gdf = _load_catchment_outline(domain_geographic)
            regional_background = _load_regional_topography_background(domain_geographic)
            river_lines = _resolve_river_lines_for_plot(
                river_trace=meshing_inputs.resolved_river_trace,
                domain_geographic=domain_geographic,
            )
            outlet_xy = None
            if domain_geographic is not None:
                x_outlet = getattr(domain_geographic, "x_outlet", None)
                y_outlet = getattr(domain_geographic, "y_outlet", None)
                if x_outlet is not None and y_outlet is not None:
                    outlet_xy = (float(x_outlet), float(y_outlet))
            regional_fig = _build_regional_context_figure(
                domain_gdf=meshing_inputs.domain_payload["gdf"],
                catchment_gdf=catchment_gdf,
                topo_background=regional_background,
                river_lines=river_lines,
                outlet_xy=outlet_xy,
            )

        if figure_path is not None and fig is not None:
            fig.savefig(figure_path)
            summary["output_figure"] = str(figure_path)
        if figure_regional_path is not None and regional_fig is not None:
            regional_fig.savefig(figure_regional_path)
            summary["output_figure_regional"] = str(figure_regional_path)
        if show_plot:
            _show_figures_blocking(fig, regional_fig)
        else:
            if fig is not None:
                plt.close(fig)
            if regional_fig is not None:
                plt.close(regional_fig)

    if summary_path is not None:
        summary["output_summary_json"] = str(summary_path)
        _write_json(summary_path, summary)

    return summary


def main(argv=None) -> int:
    args = _parse_args(argv)
    summary = run_reference_2d_zone_conformal_case_from_toml(
        args.config_file,
        section=args.section,
        output_mesh=args.output_mesh,
        output_summary_json=args.output_summary_json,
        output_figure=args.output_figure,
        output_figure_regional=args.output_figure_regional,
        show_plot=bool(args.show_plot),
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
