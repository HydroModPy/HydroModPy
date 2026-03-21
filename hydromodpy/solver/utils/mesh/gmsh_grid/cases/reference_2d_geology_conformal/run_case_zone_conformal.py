"""Run the reference 2D zone-conformal meshing case.

This script is the pedagogical entry point for the zone-conformal workflow.
It builds one planar mesh constrained by configurable inputs (geology zones,
river traces, or both), exports inspection artifacts, and keeps the focus on
geometry and visual QA before any 3D extrusion or solver coupling is
introduced.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path

from hydromodpy.solver.utils.mesh.gmsh_grid import (
    generate_zone_conformal_mesh_from_dataframe,
)
# Compatibility re-exports kept in the runner for existing callers and tests.
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.case_config import (
    _resolve_case_config,
    _resolve_constraints_mode,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.planning import (
    _build_zone_conformal_meshing_inputs,
    _clip_river_trace_to_domain,
    _resolve_river_trace_for_meshing,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.plotting import (
    _write_optional_figure_artifacts,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.reporting import (
    _build_summary,
    _finalize_summary_payload,
    _write_json,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.runner_support import (
    _build_partition_gdf,
    _parse_args,
    _resolve_config_path,
    _resolve_optional_output_path,
)

DEFAULT_CONFIG_FILE = "case_config_zone_conformal.toml"
DEFAULT_SECTION = "mesh_case"


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
    config_path = _resolve_config_path(
        config_toml,
        script_dir=Path(__file__).resolve().parent,
    )
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
    summary = _finalize_summary_payload(
        base_summary=summary,
        meshing_inputs=meshing_inputs,
        constraints_mode=constraints_mode,
        refine_interfaces=bool(meshing_inputs.zone_meshing_cfg["refine_interfaces"]),
        mesh_path=mesh_path,
    )

    summary.update(
        _write_optional_figure_artifacts(
            figure_path=figure_path,
            figure_regional_path=figure_regional_path,
            show_plot=show_plot,
            result=result,
            meshing_inputs=meshing_inputs,
            partition_gdf=partition_gdf,
            domain_geographic=domain_geographic,
        )
    )

    if summary_path is not None:
        summary["output_summary_json"] = str(summary_path)
        _write_json(summary_path, summary)

    return summary


def main(argv=None) -> int:
    args = _parse_args(
        argv,
        default_config_file=DEFAULT_CONFIG_FILE,
        default_section=DEFAULT_SECTION,
    )
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


__all__ = [
    "DEFAULT_CONFIG_FILE",
    "DEFAULT_SECTION",
    "main",
    "run_reference_2d_zone_conformal_case_from_toml",
    "_clip_river_trace_to_domain",
    "_resolve_case_config",
    "_resolve_constraints_mode",
    "_resolve_river_trace_for_meshing",
]
