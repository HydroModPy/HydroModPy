"""Run the reference 2D zone-conformal meshing case.

This script is the pedagogical entry point for the zone-conformal workflow.
It builds one planar mesh constrained by configurable inputs (geology zones,
river traces, or both), exports inspection artifacts, and keeps the focus on
geometry and visual QA before any 3D extrusion or solver coupling is
introduced.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
import json
from pathlib import Path
import tomllib
from types import SimpleNamespace
from typing import Any

import geopandas as gpd
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import rasterio

from hydromodpy.data_managers.geology.geology_config import validate_geology_config_data
from hydromodpy.data_managers.geology.geology_io import load_vector_geology_dataframe
from hydromodpy.geographic.core.river_mesh_trace import (
    build_river_mesh_trace_from_vector,
)
from hydromodpy.solver.utils.mesh.gmsh_grid import (
    generate_zone_conformal_mesh_from_dataframe,
    load_zone_meshing_domain_geometry,
    validate_zone_meshing_config_data,
    validate_zone_meshing_domain_config_data,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_base.run_case_gmsh import (
    _disable_axis_offset,
    _show_figures_blocking,
)

DEFAULT_CONFIG_FILE = "case_config_zone_conformal.toml"
DEFAULT_SECTION = "mesh_case"


def _resolve_constraints_mode(raw_value: Any) -> str:
    token = str(raw_value).strip().lower()
    if token == "":
        raise ValueError(
            "constraints_mode is required and must be one of: "
            "geology_only, rivers_only, geology_rivers."
        )
    allowed = {
        "geology_only",
        "rivers_only",
        "geology_rivers",
    }
    if token not in allowed:
        raise ValueError(
            "constraints_mode must be one of: "
            "geology_only, rivers_only, geology_rivers."
        )
    return token


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate one conformal 2D Gmsh mesh from configurable zone and river constraints."
    )
    parser.add_argument("--config-file", default=DEFAULT_CONFIG_FILE)
    parser.add_argument("--section", default=DEFAULT_SECTION)
    parser.add_argument("--output-mesh", default=None)
    parser.add_argument("--output-summary-json", default=None)
    parser.add_argument("--output-figure", default=None)
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


def _get_nested_section(
    payload: Mapping[str, Any], dotted_path: str
) -> Mapping[str, Any]:
    current: Any = payload
    for token in str(dotted_path).split("."):
        if not isinstance(current, Mapping) or token not in current:
            raise KeyError(f"Missing TOML section '{dotted_path}'")
        current = current[token]
    if not isinstance(current, Mapping):
        raise ValueError(f"TOML section '{dotted_path}' must be a mapping")
    return current


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


def _valid_geometry_mask(geometries) -> object:
    """Return one stable non-empty/non-missing mask across GeoPandas versions."""
    return (~geometries.is_empty) & (~geometries.isna())


def _resolve_river_trace_for_meshing(
    *,
    river_trace: object | None,
    domain_geographic: object | None,
    rivers_cfg: Mapping[str, Any] | None,
    config_path: Path,
) -> object | None:
    """Resolve the in-memory river trace payload passed to the mesher.

    Priority order:
    1. explicit ``river_trace`` argument,
    2. source configured in ``[<section>.rivers]``.
    """
    if river_trace is not None:
        return river_trace
    cfg = dict(rivers_cfg or {})
    source = str(cfg.get("source", "domain_geographic")).strip().lower()

    if source == "file":
        raw_path = cfg.get("path")
        if raw_path is None:
            return None
        file_path = Path(str(raw_path)).expanduser()
        if not file_path.is_absolute():
            file_path = (config_path.parent / file_path).resolve()
        if not file_path.exists():
            return None
        try:
            return build_river_mesh_trace_from_vector(
                vector_path=file_path,
                source_kind="file",
                clip_polygon_path=None,
            )
        except Exception:
            try:
                rivers = gpd.read_file(str(file_path))
                if rivers.empty:
                    return None
                rivers = rivers[_valid_geometry_mask(rivers.geometry)].copy()
                if rivers.empty:
                    return None
                return SimpleNamespace(lines=tuple(rivers.geometry.tolist()))
            except Exception:
                return None

    if domain_geographic is None:
        return None
    from_context = getattr(domain_geographic, "river_mesh_trace", None)
    return from_context


def _clip_river_trace_to_domain(
    *,
    river_trace: object | None,
    domain_geometry: object,
) -> object | None:
    if river_trace is None:
        return None
    lines_attr = getattr(river_trace, "lines", None)
    if lines_attr is None:
        return river_trace

    clipped_lines: list[object] = []
    for geometry in lines_attr:
        if geometry is None:
            continue
        try:
            clipped = geometry.intersection(domain_geometry)
        except Exception:
            clipped = geometry
        clipped_lines.extend(_iter_line_geometries((clipped,)))
    if not clipped_lines:
        return None
    return SimpleNamespace(lines=tuple(clipped_lines))


def _filter_river_trace_by_min_segment_length(
    *,
    river_trace: object | None,
    min_segment_length: float,
) -> object | None:
    if river_trace is None:
        return None
    if min_segment_length <= 0.0:
        return river_trace
    lines_attr = getattr(river_trace, "lines", None)
    if lines_attr is None:
        return river_trace

    kept_lines: list[object] = []
    for line in _iter_line_geometries(lines_attr):
        length = float(getattr(line, "length", 0.0))
        if length >= min_segment_length:
            kept_lines.append(line)
    if not kept_lines:
        return None
    return SimpleNamespace(lines=tuple(kept_lines))


def _validate_rivers_case_config(
    config_data: Mapping[str, Any],
    *,
    section: str,
) -> dict[str, Any]:
    if not isinstance(config_data, Mapping):
        raise ValueError(f"[{section}.rivers] configuration must be a mapping")
    raw = dict(config_data)
    source = str(raw.get("source", "domain_geographic")).strip().lower()
    if source not in {"domain_geographic", "file"}:
        raise ValueError(
            f"[{section}.rivers].source must be 'domain_geographic' or 'file', got '{source}'."
        )

    path_value = raw.get("path")
    path_text = None if path_value is None else str(path_value).strip()
    if source == "file" and not path_text:
        raise ValueError(f"[{section}.rivers].path is required when source='file'.")

    clip_to_domain = raw.get("clip_to_domain", True)
    if not isinstance(clip_to_domain, bool):
        raise ValueError(f"[{section}.rivers].clip_to_domain must be a boolean.")

    min_segment_length_raw = raw.get("min_segment_length", 0.0)
    try:
        min_segment_length = float(min_segment_length_raw)
    except Exception as exc:
        raise ValueError(
            f"[{section}.rivers].min_segment_length must be a number, got '{min_segment_length_raw}'."
        ) from exc
    if min_segment_length < 0.0:
        raise ValueError(f"[{section}.rivers].min_segment_length must be >= 0.")

    snap_tolerance_raw = raw.get("snap_tolerance", 0.0)
    try:
        snap_tolerance = float(snap_tolerance_raw)
    except Exception as exc:
        raise ValueError(
            f"[{section}.rivers].snap_tolerance must be a number, got '{snap_tolerance_raw}'."
        ) from exc
    if snap_tolerance < 0.0:
        raise ValueError(f"[{section}.rivers].snap_tolerance must be >= 0.")

    return {
        "source": source,
        "path": None if not path_text else path_text,
        "clip_to_domain": clip_to_domain,
        "min_segment_length": min_segment_length,
        "snap_tolerance": snap_tolerance,
    }


def _resolve_case_config(
    config_toml: Path, *, section: str = DEFAULT_SECTION
) -> dict[str, Any]:
    payload = tomllib.loads(config_toml.read_text(encoding="utf-8-sig"))
    section_cfg = dict(_get_nested_section(payload, section))
    if "mesh_mode" in section_cfg:
        raise ValueError(
            "mesh_mode is no longer supported; use constraints_mode with one of: "
            "geology_only, rivers_only, geology_rivers."
        )
    constraints_mode = _resolve_constraints_mode(section_cfg.get("constraints_mode"))
    domain_cfg = validate_zone_meshing_domain_config_data(
        dict(section_cfg.get("domain", {}))
    )
    zone_meshing_cfg = validate_zone_meshing_config_data(
        dict(section_cfg.get("zone_meshing", {}))
    )
    geology_cfg = None
    if constraints_mode in {"geology_only", "geology_rivers"}:
        geology_cfg = validate_geology_config_data(dict(section_cfg.get("geology", {})))
    rivers_cfg = None
    if constraints_mode in {"rivers_only", "geology_rivers"}:
        rivers_cfg = _validate_rivers_case_config(
            dict(section_cfg.get("rivers", {})),
            section=section,
        )

    return {
        "constraints_mode": constraints_mode,
        "geology": geology_cfg,
        "rivers": rivers_cfg,
        "domain": domain_cfg,
        "zone_meshing": zone_meshing_cfg,
        "output_mesh": section_cfg.get("output_mesh"),
        "output_summary_json": section_cfg.get("output_summary_json"),
        "output_figure": section_cfg.get("output_figure"),
    }


def _build_domain_zone_dataframe(
    *,
    domain_payload: Mapping[str, Any],
) -> tuple[dict[str, Any], gpd.GeoDataFrame]:
    domain_gdf = domain_payload["gdf"][["geometry"]].copy()
    domain_gdf = domain_gdf.explode(index_parts=False).reset_index(drop=True)
    domain_gdf = domain_gdf[_valid_geometry_mask(domain_gdf.geometry)].copy()
    if domain_gdf.empty:
        raise ValueError("domain geometry produced no usable polygon for meshing")
    domain_gdf["zone_key"] = "domain"
    summary = dict(domain_payload.get("summary", {}))
    source_path = summary.get("domain_source_path")
    source_payload = {
        "field_id": "domain_zones",
        "source_kind": "domain",
        "source_path": "<domain>" if source_path is None else str(source_path),
        "n_source_features_before_domain_clip": int(len(domain_gdf)),
    }
    return source_payload, domain_gdf


def _load_clipped_geology_dataframe(
    *,
    geology_cfg: Mapping[str, Any],
    domain_cfg: Mapping[str, Any],
    config_path: Path,
    domain_geographic: object | None,
):
    payload = load_vector_geology_dataframe(
        geology_cfg,
        config_path=config_path,
        zone_key_column="zone_key",
    )
    gdf = payload["gdf"].copy()
    payload["n_source_features_before_domain_clip"] = int(len(gdf))
    domain_payload = load_zone_meshing_domain_geometry(
        domain_cfg,
        config_path=config_path,
        domain_geographic=domain_geographic,
        target_crs=gdf.crs,
        validate=False,
    )
    clipped = gpd.clip(gdf, domain_payload["gdf"])
    clipped = clipped[_valid_geometry_mask(clipped.geometry)].copy()
    if clipped.empty:
        raise ValueError(
            "The selected domain geometry does not intersect the geology source"
        )
    return payload, clipped, domain_payload


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


def _iter_line_geometries(geometries: Iterable[object]) -> list[object]:
    out: list[object] = []
    for geometry in geometries:
        if geometry is None:
            continue
        geom_type = str(getattr(geometry, "geom_type", ""))
        if geom_type == "LineString":
            if not bool(getattr(geometry, "is_empty", True)):
                out.append(geometry)
            continue
        if geom_type == "MultiLineString":
            parts = getattr(geometry, "geoms", ())
            for part in parts:
                if not bool(getattr(part, "is_empty", True)):
                    out.append(part)
            continue
        if geom_type == "GeometryCollection":
            out.extend(_iter_line_geometries(getattr(geometry, "geoms", ())))
    return out


def _iter_river_lines(river_trace: object | None) -> list[object]:
    if river_trace is None:
        return []
    lines = getattr(river_trace, "lines", None)
    if lines is None:
        return []
    return _iter_line_geometries(lines)


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


def _build_summary(
    *,
    result,
    source_payload: Mapping[str, Any],
    clipped_gdf: gpd.GeoDataFrame,
    domain_payload: Mapping[str, Any],
) -> dict[str, Any]:
    zone_feature_counts = (
        clipped_gdf["zone_key"].astype(str).value_counts().sort_index()
    )
    summary = dict(result.summary)
    summary.update(
        {
            "field_id": str(source_payload["field_id"]),
            "source_kind": str(source_payload["source_kind"]),
            "source_path": str(source_payload["source_path"]),
            "n_source_features_total": int(
                source_payload.get(
                    "n_source_features_before_domain_clip", len(clipped_gdf)
                )
            ),
            "n_source_features_clipped": int(len(clipped_gdf)),
            "zone_feature_counts": {
                str(key): int(value) for key, value in zone_feature_counts.items()
            },
        }
    )
    summary.update(
        {str(key): value for key, value in dict(domain_payload["summary"]).items()}
    )
    return summary


def _build_constraints_qa_contract(
    *,
    summary: Mapping[str, Any],
    constraints_mode: str,
    refine_interfaces: bool,
) -> dict[str, Any]:
    uses_geology_constraints = constraints_mode in {"geology_only", "geology_rivers"}
    uses_river_constraints = constraints_mode in {"rivers_only", "geology_rivers"}

    zone_count = int(len(tuple(summary.get("zone_keys", ()))))
    interface_group_count = int(summary.get("interface_group_count", 0))
    river_payload = (
        dict(summary.get("river_trace", {}))
        if isinstance(summary.get("river_trace"), Mapping)
        else {}
    )
    river_trace_provided = bool(river_payload.get("provided", False))
    river_line_count = int(river_payload.get("line_count", 0))
    river_curve_count = int(river_payload.get("curve_count", 0))
    river_embed_success = int(river_payload.get("embedded_surface_curve_pairs", 0))
    river_embed_failures = int(river_payload.get("embed_failures", 0))
    river_refined = bool(river_payload.get("refined_with_interface_field", False))
    river_curve_group_present = any(
        str(group.get("name", "")) == "river::trace"
        for group in summary.get("curve_physical_groups", ())
        if isinstance(group, Mapping)
    )

    embed_attempts = int(river_embed_success + river_embed_failures)
    embed_success_rate = (
        None
        if embed_attempts <= 0
        else round(float(river_embed_success) / float(embed_attempts), 12)
    )
    embed_pairs_per_curve = (
        None
        if river_curve_count <= 0
        else round(float(river_embed_success) / float(river_curve_count), 12)
    )

    thresholds = {
        "min_zone_count": 1 if uses_geology_constraints else 0,
        "min_interface_group_count": 1 if uses_geology_constraints else 0,
        "min_river_curve_count": 1 if uses_river_constraints else 0,
        "min_embedded_surface_curve_pairs": 1 if uses_river_constraints else 0,
        "require_refinement_when_refine_interfaces_true": bool(
            uses_river_constraints and refine_interfaces
        ),
    }
    metrics = {
        "zone_count": zone_count,
        "interface_group_count": interface_group_count,
        "river_trace_provided": river_trace_provided,
        "river_line_count": river_line_count,
        "river_curve_count": river_curve_count,
        "river_curve_group_present": river_curve_group_present,
        "river_embed_success_pairs": river_embed_success,
        "river_embed_failures": river_embed_failures,
        "river_embed_attempts": embed_attempts,
        "river_embed_success_rate": embed_success_rate,
        "river_embed_pairs_per_curve": embed_pairs_per_curve,
        "river_refined_with_interface_field": river_refined,
        "refine_interfaces_config": bool(refine_interfaces),
    }
    checks: dict[str, bool] = {}
    if uses_geology_constraints:
        checks["has_zone_partition"] = bool(zone_count >= int(thresholds["min_zone_count"]))
        checks["has_geology_interfaces"] = bool(
            interface_group_count >= int(thresholds["min_interface_group_count"])
        )
    if uses_river_constraints:
        checks["river_trace_provided"] = bool(river_trace_provided)
        checks["river_curves_generated"] = bool(
            river_curve_count >= int(thresholds["min_river_curve_count"])
            and river_line_count > 0
        )
        checks["river_curve_group_present"] = bool(river_curve_group_present)
        checks["river_embedded_on_surfaces"] = bool(
            river_embed_success >= int(thresholds["min_embedded_surface_curve_pairs"])
        )
        checks["river_refinement_consistent_with_config"] = bool(
            (not bool(thresholds["require_refinement_when_refine_interfaces_true"]))
            or river_refined
        )
    if constraints_mode == "geology_rivers":
        checks["geology_and_river_constraints_coexist"] = bool(
            checks.get("has_geology_interfaces", False)
            and checks.get("river_curves_generated", False)
        )

    return {
        "contract_version": "constraints_qa_v1",
        "mode": str(constraints_mode),
        "thresholds": thresholds,
        "metrics": metrics,
        "checks": checks,
        "overall_pass": bool(all(checks.values())),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def run_reference_2d_zone_conformal_case_from_toml(
    config_toml: str | Path,
    *,
    section: str = DEFAULT_SECTION,
    output_mesh: str | Path | None = None,
    output_summary_json: str | Path | None = None,
    output_figure: str | Path | None = None,
    river_trace: object | None = None,
    domain_geographic: object | None = None,
    show_plot: bool = False,
) -> dict[str, Any]:
    config_path = _resolve_config_path(config_toml)
    cfg = _resolve_case_config(config_path, section=section)
    constraints_mode = str(cfg["constraints_mode"])
    uses_geology_constraints = constraints_mode in {"geology_only", "geology_rivers"}
    uses_river_constraints = constraints_mode in {"rivers_only", "geology_rivers"}

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

    if mesh_path is None:
        raise ValueError(
            "An output mesh path is required for the conformal reference case"
        )

    if uses_geology_constraints:
        if cfg["geology"] is None:
            raise ValueError(
                "constraints_mode requires one "
                f"[{section}.geology] block for mode '{constraints_mode}'."
            )
        source_payload, clipped_gdf, domain_payload = _load_clipped_geology_dataframe(
            geology_cfg=cfg["geology"],
            domain_cfg=cfg["domain"],
            config_path=config_path,
            domain_geographic=domain_geographic,
        )
    else:
        domain_payload = load_zone_meshing_domain_geometry(
            cfg["domain"],
            config_path=config_path,
            domain_geographic=domain_geographic,
            target_crs=None,
            validate=False,
        )
        source_payload, clipped_gdf = _build_domain_zone_dataframe(
            domain_payload=domain_payload,
        )

    resolved_river_trace = None
    if uses_river_constraints:
        rivers_cfg = cfg.get("rivers") or {}
        resolved_river_trace = _resolve_river_trace_for_meshing(
            river_trace=river_trace,
            domain_geographic=domain_geographic,
            rivers_cfg=rivers_cfg,
            config_path=config_path,
        )
        if bool(rivers_cfg.get("clip_to_domain", True)):
            resolved_river_trace = _clip_river_trace_to_domain(
                river_trace=resolved_river_trace,
                domain_geometry=domain_payload["geometry"],
            )
        resolved_river_trace = _filter_river_trace_by_min_segment_length(
            river_trace=resolved_river_trace,
            min_segment_length=float(rivers_cfg.get("min_segment_length", 0.0)),
        )
        if resolved_river_trace is None:
            raise ValueError(
                "constraints_mode requires one usable river trace for mode "
                f"'{constraints_mode}'. Provide [{section}.rivers] with source='file', "
                "or provide domain_geographic with one river_mesh_trace, "
                "or pass an explicit river_trace."
            )
    river_trace_for_meshing = resolved_river_trace if uses_river_constraints else None

    result = generate_zone_conformal_mesh_from_dataframe(
        clipped_gdf,
        output_path=mesh_path,
        zone_key_column="zone_key",
        domain_geometry=domain_payload["geometry"],
        algorithm=str(cfg["zone_meshing"]["algorithm"]),
        global_size=float(cfg["zone_meshing"]["global_size"]),
        min_size=cfg["zone_meshing"]["min_size"],
        max_size=cfg["zone_meshing"]["max_size"],
        simplify_tolerance=float(cfg["zone_meshing"]["simplify_tolerance"]),
        heal_tolerance=float(cfg["zone_meshing"]["heal_tolerance"]),
        min_polygon_area=float(cfg["zone_meshing"]["min_polygon_area"]),
        refine_interfaces=bool(cfg["zone_meshing"]["refine_interfaces"]),
        interface_size=cfg["zone_meshing"]["interface_size"],
        interface_distance=cfg["zone_meshing"]["interface_distance"],
        interface_sampling=int(cfg["zone_meshing"]["interface_sampling"]),
        river_trace=river_trace_for_meshing,
        model_name=f"reference_2d_zone_conformal_{constraints_mode}",
    )

    partition_gdf = _build_partition_gdf(result.partition, crs=clipped_gdf.crs)
    summary = _build_summary(
        result=result,
        source_payload=source_payload,
        clipped_gdf=clipped_gdf,
        domain_payload=domain_payload,
    )
    summary["constraints_mode"] = constraints_mode
    summary["constraints_qa"] = _build_constraints_qa_contract(
        summary=summary,
        constraints_mode=constraints_mode,
        refine_interfaces=bool(cfg["zone_meshing"]["refine_interfaces"]),
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
    if uses_river_constraints and cfg["rivers"] is not None:
        summary["rivers_config"] = {
            "source": str(cfg["rivers"]["source"]),
            "path": cfg["rivers"]["path"],
            "clip_to_domain": bool(cfg["rivers"]["clip_to_domain"]),
            "min_segment_length": float(cfg["rivers"]["min_segment_length"]),
            "snap_tolerance": float(cfg["rivers"]["snap_tolerance"]),
        }
    summary["output_mesh"] = str(mesh_path)

    if figure_path is not None or show_plot:
        fig = _build_figure(
            clipped_gdf=clipped_gdf,
            partition_gdf=partition_gdf,
            domain_gdf=domain_payload["gdf"],
            mesh=result.mesh,
            domain_bounds=list(domain_payload["geometry"].bounds),
            domain_area=float(domain_payload["summary"]["domain_area"]),
            domain_kind=str(domain_payload["summary"]["domain_kind"]),
            interface_refinement=(
                dict(
                    result.summary.get("mesh_size_fields", {}).get(
                        "interface_refinement", {}
                    )
                )
            ),
            domain_geographic=domain_geographic,
            river_trace=resolved_river_trace,
        )
        if figure_path is not None:
            fig.savefig(figure_path)
            summary["output_figure"] = str(figure_path)
        if show_plot:
            _show_figures_blocking(fig)
        else:
            plt.close(fig)

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
        show_plot=bool(args.show_plot),
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
