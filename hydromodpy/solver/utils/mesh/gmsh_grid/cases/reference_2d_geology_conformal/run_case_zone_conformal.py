"""Run the reference 2D zone-conformal meshing case.

This script is the pedagogical entry point for the zone-conformal workflow.
It builds one planar mesh constrained by configurable inputs (geology zones,
river traces, or both), exports inspection artifacts, and keeps the focus on
geometry and visual QA before any 3D extrusion or solver coupling is
introduced.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from hydromodpy.solver.utils.mesh.gmsh_grid._trace import trace_mesh_stage
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.case_config import (
    _resolve_case_config,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.execution import (
    _run_zone_conformal_meshing,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.planning import (
    _build_zone_conformal_meshing_inputs,
    _load_watershed_geometry,
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


@dataclass(frozen=True)
class ZoneConformalCaseRuntimeArtifacts:
    """Return payload used by integrated workflows that keep the mesh in memory."""

    summary: dict[str, Any]
    mesh: object


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
    return_runtime_artifacts: bool = False,
) -> dict[str, Any] | ZoneConformalCaseRuntimeArtifacts:
    """Run the pedagogical conformal case from TOML or an in-memory override.

    This function is the user-facing bridge between the case configuration and
    the lower-level `zone_meshing` engine. Its responsibilities are:

    - resolve and validate the case config;
    - prepare the meshing inputs from geology / rivers / domain context;
    - launch the actual meshing;
    - assemble summary and optional figure artifacts.
    """
    trace_mesh_stage("zone_conformal.run.start", config_toml=config_toml, section=section)
    config_path = _resolve_config_path(
        config_toml,
        script_dir=Path(__file__).resolve().parent,
    )
    trace_mesh_stage("zone_conformal.config.resolved", config_path=config_path)
    cfg = _resolve_case_config(
        config_path,
        section=section,
        section_data_override=section_data_override,
    )
    trace_mesh_stage("zone_conformal.config.loaded")
    meshing_inputs = _build_zone_conformal_meshing_inputs(
        cfg=cfg,
        config_path=config_path,
        river_trace=river_trace,
        domain_geographic=domain_geographic,
    )
    trace_mesh_stage(
        "zone_conformal.inputs.built",
        zone_features=len(meshing_inputs.zone_gdf),
        constraints_mode=meshing_inputs.constraints_mode_label,
    )
    constraints_mode = str(meshing_inputs.constraints_mode_label)

    mesh_path = _resolve_optional_output_path(
        config_path,
        cfg.output_mesh,
        None if output_mesh is None else str(output_mesh),
    )
    summary_path = _resolve_optional_output_path(
        config_path,
        cfg.output_summary_json,
        None if output_summary_json is None else str(output_summary_json),
    )
    figure_path = _resolve_optional_output_path(
        config_path,
        cfg.output_figure,
        None if output_figure is None else str(output_figure),
    )
    figure_regional_path = _resolve_optional_output_path(
        config_path,
        cfg.output_figure_regional,
        None if output_figure_regional is None else str(output_figure_regional),
    )

    if mesh_path is None:
        raise ValueError("An output mesh path is required for the conformal reference case")
    trace_mesh_stage("zone_conformal.outputs.resolved", mesh_path=mesh_path)

    result = _run_zone_conformal_meshing(
        meshing_inputs=meshing_inputs,
        mesh_path=mesh_path,
    )
    trace_mesh_stage(
        "zone_conformal.meshing.done",
        n_cells=result.mesh.n_cells,
        output_mesh=result.output_path,
    )

    partition_gdf = _build_partition_gdf(result.partition, crs=meshing_inputs.zone_gdf.crs)
    trace_mesh_stage("zone_conformal.partition_gdf.built", n_faces=len(partition_gdf))
    watershed_geometry = None
    if (
        domain_geographic is not None
        and getattr(domain_geographic, "watershed_shp", None) is not None
    ):
        try:
            watershed_geometry = _load_watershed_geometry(
                domain_geographic=domain_geographic,
                target_crs=meshing_inputs.effective_domain_payload.gdf.crs,
            )
        except Exception:
            watershed_geometry = None
    summary = _build_summary(
        result=result,
        source_payload=meshing_inputs.source_payload,
        clipped_gdf=meshing_inputs.diagnostics.source_plot_gdf,
        domain_payload=meshing_inputs.effective_domain_payload,
        watershed_geometry=watershed_geometry,
    )
    trace_mesh_stage("zone_conformal.summary.built")
    summary = _finalize_summary_payload(
        base_summary=summary,
        meshing_inputs=meshing_inputs,
        constraints_mode=constraints_mode,
        refine_interfaces=meshing_inputs.zone_meshing_cfg.refine_interfaces,
        mesh_path=mesh_path,
    )
    trace_mesh_stage("zone_conformal.summary.finalized")

    summary.update(
        _write_optional_figure_artifacts(
            figure_path=figure_path,
            figure_regional_path=figure_regional_path,
            show_plot=show_plot,
            result=result,
            meshing_inputs=meshing_inputs,
            partition_gdf=partition_gdf,
            domain_geographic=domain_geographic,
            figure_dpi=cfg.figure_dpi,
            figure_regional_dpi=cfg.figure_regional_dpi,
        )
    )
    trace_mesh_stage("zone_conformal.figures.done")

    if summary_path is not None:
        summary["output_summary_json"] = str(summary_path)
        _write_json(summary_path, summary)
        trace_mesh_stage("zone_conformal.summary.written", summary_path=summary_path)

    trace_mesh_stage("zone_conformal.run.done")
    if return_runtime_artifacts:
        return ZoneConformalCaseRuntimeArtifacts(
            summary=dict(summary),
            mesh=result.mesh,
        )
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
]
