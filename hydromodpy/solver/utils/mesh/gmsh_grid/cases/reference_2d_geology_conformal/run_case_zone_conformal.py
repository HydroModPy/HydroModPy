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
    _resolve_river_trace_for_meshing,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.plotting import (
    _build_figure,
    _build_geographic_mesh_figure,
    _build_regional_context_figure,
    _build_zone_color_map,
    _draw_domain_outline,
    _draw_legend_panel,
    _draw_mesh_edges,
    _draw_river_lines,
    _load_catchment_outline,
    _load_regional_topography_background,
    _load_topography_background,
    _plot_zone_panel,
    _resolve_river_lines_for_plot,
    _set_panel_limits,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.reporting import (
    _build_constraints_qa_contract,
    _build_summary,
    _write_json,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_base.run_case_gmsh import _show_figures_blocking

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
