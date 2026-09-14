"""Production entry points for zone-conformal catchment meshing.

This module holds the reusable core shared by the production launcher and the
pedagogical demo case:

- ``run_zone_conformal_meshing`` resolves the config, builds the meshing inputs,
  runs the Gmsh generation and assembles the finalized summary. It returns every
  intermediate artifact so callers can add their own outputs (figures, reports).
- ``run_zone_conformal_meshing_from_toml`` is the thin production entry used by
  the mesh-catchment launcher. It writes the summary JSON sidecar and returns the
  summary (optionally with the in-memory mesh). It deliberately does not build any
  plotting artifact; that concern stays in the demo case.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.spatial.mesh.gmsh_grid.trace import trace_mesh_stage
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.orchestration.case_config import (
    _resolve_case_config,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.orchestration.contracts import (
    ZoneConformalCaseConfig,
    ZoneConformalMeshingInputs,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.orchestration.execution import (
    _run_zone_conformal_meshing,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.orchestration.output_paths import (
    _resolve_config_path,
    _resolve_optional_output_path,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.orchestration.planning import (
    _build_zone_conformal_meshing_inputs,
    _load_watershed_geometry,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.orchestration.plotting import (
    _build_partition_gdf,
    _write_optional_figure_artifacts,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.orchestration.reporting import (
    _build_summary,
    _finalize_summary_payload,
    _write_json,
)

DEFAULT_SECTION = "mesh_case"


@dataclass(frozen=True)
class ZoneConformalMeshingRun:
    """Full result of one meshing run, before any output artifact is written."""

    summary: dict[str, Any]
    mesh: object
    result: object
    meshing_inputs: ZoneConformalMeshingInputs
    cfg: ZoneConformalCaseConfig
    config_path: Path
    mesh_path: Path
    summary_path: Path | None
    watershed_geometry: object | None


@dataclass(frozen=True)
class ZoneConformalMeshingRuntimeArtifacts:
    """Return payload for integrated workflows that keep the mesh in memory."""

    summary: dict[str, Any]
    mesh: object


def run_zone_conformal_meshing(
    config_toml: str | Path,
    *,
    section: str = DEFAULT_SECTION,
    section_data_override: Mapping[str, Any] | None = None,
    output_mesh: str | Path | None = None,
    output_summary_json: str | Path | None = None,
    river_trace: object | None = None,
    geographic_features: object | None = None,
    domain_geographic: object | None = None,
    extra_size_fields: tuple = (),
    script_dir: Path | None = None,
) -> ZoneConformalMeshingRun:
    """Resolve config, build inputs, run meshing and assemble the finalized summary.

    This is the reusable meshing core. It writes the mesh file but no report or
    figure. Callers decide which output artifacts to add on top of the returned
    :class:`ZoneConformalMeshingRun`.
    """
    trace_mesh_stage("zone_conformal.run.start", config_toml=config_toml, section=section)
    config_path = _resolve_config_path(config_toml, script_dir=script_dir)
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
        geographic_features=geographic_features,
        domain_geographic=domain_geographic,
        extra_size_fields=tuple(extra_size_fields),
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

    return ZoneConformalMeshingRun(
        summary=summary,
        mesh=result.mesh,
        result=result,
        meshing_inputs=meshing_inputs,
        cfg=cfg,
        config_path=config_path,
        mesh_path=mesh_path,
        summary_path=summary_path,
        watershed_geometry=watershed_geometry,
    )


def run_zone_conformal_meshing_from_toml(
    config_toml: str | Path,
    *,
    section: str = DEFAULT_SECTION,
    section_data_override: Mapping[str, Any] | None = None,
    output_mesh: str | Path | None = None,
    output_summary_json: str | Path | None = None,
    output_figure: str | Path | None = None,
    output_figure_regional: str | Path | None = None,
    river_trace: object | None = None,
    geographic_features: object | None = None,
    domain_geographic: object | None = None,
    extra_size_fields: tuple = (),
    show_plot: bool = False,
    return_runtime_artifacts: bool = False,
    script_dir: Path | None = None,
) -> dict[str, Any] | ZoneConformalMeshingRuntimeArtifacts:
    """Run the reusable meshing core, then write the overview figures and JSON sidecar.

    This is the production entry consumed by the mesh-catchment launcher. It writes
    the overview figures when ``output_figure``/``output_figure_regional`` resolve to
    a path (same content and gating as the demo case), then the summary JSON sidecar.
    """
    run = run_zone_conformal_meshing(
        config_toml,
        section=section,
        section_data_override=section_data_override,
        output_mesh=output_mesh,
        output_summary_json=output_summary_json,
        river_trace=river_trace,
        geographic_features=geographic_features,
        domain_geographic=domain_geographic,
        extra_size_fields=extra_size_fields,
        script_dir=script_dir,
    )
    summary = dict(run.summary)

    figure_path = _resolve_optional_output_path(
        run.config_path,
        run.cfg.output_figure,
        None if output_figure is None else str(output_figure),
    )
    figure_regional_path = _resolve_optional_output_path(
        run.config_path,
        run.cfg.output_figure_regional,
        None if output_figure_regional is None else str(output_figure_regional),
    )
    partition_gdf = _build_partition_gdf(run.result.partition, crs=run.meshing_inputs.zone_gdf.crs)
    trace_mesh_stage("zone_conformal.partition_gdf.built", n_faces=len(partition_gdf))
    summary.update(
        _write_optional_figure_artifacts(
            figure_path=figure_path,
            figure_regional_path=figure_regional_path,
            show_plot=show_plot,
            result=run.result,
            meshing_inputs=run.meshing_inputs,
            partition_gdf=partition_gdf,
            domain_geographic=domain_geographic,
            figure_dpi=run.cfg.figure_dpi,
            figure_regional_dpi=run.cfg.figure_regional_dpi,
        )
    )
    trace_mesh_stage("zone_conformal.figures.done")

    if run.summary_path is not None:
        summary["output_summary_json"] = str(run.summary_path)
        _write_json(run.summary_path, summary)
        trace_mesh_stage("zone_conformal.summary.written", summary_path=run.summary_path)

    trace_mesh_stage("zone_conformal.run.done")
    if return_runtime_artifacts:
        return ZoneConformalMeshingRuntimeArtifacts(summary=dict(summary), mesh=run.mesh)
    return summary


__all__ = [
    "DEFAULT_SECTION",
    "ZoneConformalMeshingRun",
    "ZoneConformalMeshingRuntimeArtifacts",
    "run_zone_conformal_meshing",
    "run_zone_conformal_meshing_from_toml",
]
