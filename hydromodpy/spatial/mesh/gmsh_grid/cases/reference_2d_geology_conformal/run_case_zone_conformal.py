"""Run the reference 2D zone-conformal meshing case.

This script is the pedagogical entry point for the zone-conformal workflow.
It builds one planar mesh constrained by configurable inputs (geology zones,
river traces, or both), exports inspection artifacts, and keeps the focus on
geometry and visual QA before any 3D extrusion or solver coupling is
introduced.

The whole run is delegated to the reusable orchestration core in
``zone_meshing.orchestration``, which produces the mesh, the finalized summary,
the overview figures and the summary JSON sidecar. This demo only re-labels the
runtime payload for pedagogical callers.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_2d_geology_conformal.runner_support import (
    _parse_args,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.orchestration.runner import (
    run_zone_conformal_meshing_from_toml,
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
    geographic_features: object | None = None,
    domain_geographic: object | None = None,
    extra_size_fields: tuple = (),
    show_plot: bool = False,
    return_runtime_artifacts: bool = False,
) -> dict[str, Any] | ZoneConformalCaseRuntimeArtifacts:
    """Run the pedagogical conformal case from TOML or an in-memory override.

    This function is the user-facing bridge between the case configuration and
    the lower-level `zone_meshing` engine. It delegates the whole run (meshing,
    summary, overview figures and JSON) to the reusable orchestration core; the
    default config file is resolved relative to this case directory.
    """
    result = run_zone_conformal_meshing_from_toml(
        config_toml,
        section=section,
        section_data_override=section_data_override,
        output_mesh=output_mesh,
        output_summary_json=output_summary_json,
        output_figure=output_figure,
        output_figure_regional=output_figure_regional,
        river_trace=river_trace,
        geographic_features=geographic_features,
        domain_geographic=domain_geographic,
        extra_size_fields=tuple(extra_size_fields),
        show_plot=show_plot,
        return_runtime_artifacts=return_runtime_artifacts,
        script_dir=Path(__file__).resolve().parent,
    )
    if return_runtime_artifacts:
        return ZoneConformalCaseRuntimeArtifacts(
            summary=dict(result.summary),
            mesh=result.mesh,
        )
    return result


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
