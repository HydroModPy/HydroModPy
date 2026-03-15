"""Run the reference 2D zone-conformal meshing case on Brittany geology.

This script is the pedagogical entry point for the "mesh follows geology
boundaries" workflow. It builds one planar mesh constrained by polygonal zones,
exports inspection artifacts, and keeps the focus on geometry and visual QA
before any 3D extrusion or solver coupling is introduced.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import tomllib
from typing import Any

import geopandas as gpd
from matplotlib import pyplot as plt
from matplotlib.patches import Patch
import numpy as np

from hydromodpy.data_managers.geology.geology_config import validate_geology_config_data
from hydromodpy.data_managers.geology.geology_io import load_vector_geology_dataframe
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
DEFAULT_SECTION = "case"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate one conformal 2D Gmsh mesh on a clipped Brittany geology subset."
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


def _resolve_case_config(config_toml: Path, *, section: str = "case") -> dict[str, Any]:
    payload = tomllib.loads(config_toml.read_text(encoding="utf-8-sig"))
    section_cfg = dict(_get_nested_section(payload, section))
    geology_cfg = validate_geology_config_data(dict(section_cfg.get("geology", {})))
    domain_cfg = validate_zone_meshing_domain_config_data(
        dict(section_cfg.get("domain", {}))
    )
    zone_meshing_cfg = validate_zone_meshing_config_data(
        dict(section_cfg.get("zone_meshing", {}))
    )

    return {
        "geology": geology_cfg,
        "domain": domain_cfg,
        "zone_meshing": zone_meshing_cfg,
        "output_mesh": section_cfg.get("output_mesh"),
        "output_summary_json": section_cfg.get("output_summary_json"),
        "output_figure": section_cfg.get("output_figure"),
    }


def _load_clipped_geology_dataframe(
    *, geology_cfg: Mapping[str, Any], domain_cfg: Mapping[str, Any], config_path: Path
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
        target_crs=gdf.crs,
        validate=False,
    )
    clipped = gpd.clip(gdf, domain_payload["gdf"])
    clipped = clipped[~clipped.geometry.is_empty & clipped.geometry.notna()].copy()
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
        title="Geology zones",
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
):
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
        title="Clipped geology source polygons",
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
    fig.suptitle("Reference 2D geology-conformal Gmsh mesh", fontsize=19)
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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def run_reference_2d_geology_conformal_case_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
    output_mesh: str | Path | None = None,
    output_summary_json: str | Path | None = None,
    output_figure: str | Path | None = None,
    show_plot: bool = False,
) -> dict[str, Any]:
    config_path = _resolve_config_path(config_toml)
    cfg = _resolve_case_config(config_path, section=section)

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

    source_payload, clipped_gdf, domain_payload = _load_clipped_geology_dataframe(
        geology_cfg=cfg["geology"],
        domain_cfg=cfg["domain"],
        config_path=config_path,
    )
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
        model_name="reference_2d_geology_conformal",
    )

    partition_gdf = _build_partition_gdf(result.partition, crs=clipped_gdf.crs)
    summary = _build_summary(
        result=result,
        source_payload=source_payload,
        clipped_gdf=clipped_gdf,
        domain_payload=domain_payload,
    )
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
    summary = run_reference_2d_geology_conformal_case_from_toml(
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
