"""Run the reference 2D geology-to-mesh workflow on a planar Gmsh mesh.

This case remains the didactic entry point for the Gmsh backend. The runner
itself is intentionally short: config resolution, plotting helpers, and summary
building now live in dedicated modules so this file reads as the workflow
orchestrator.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from matplotlib import pyplot as plt

from hydromodpy.spatial.field.core.field_param import FieldParam
from hydromodpy.spatial.field.geology.geology_field import GeologyField
from hydromodpy.spatial.mesh.gmsh_grid import GmshPlanarMesh2D
from hydromodpy.spatial.mesh.gmsh_grid.cases._common import (
    optional_case_output_path,
    write_case_json,
)
from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_2d_geology_base.case_config import (
    build_reference_mesh_from_toml,
    resolve_reference_case_config,
    resolve_reference_case_config_path,
)
from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_2d_geology_base.plotting import (
    build_reference_case_figure,
    show_figures_blocking,
)
from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_2d_geology_base.reporting import (
    build_reference_case_summary,
)
from hydromodpy.spatial.mesh.gmsh_grid.plotting_utils import (
    ensure_interactive_backend_for_show,
)

plt.switch_backend("Agg")


DEFAULT_CONFIG_FILE = "case_config_gmsh.toml"
DEFAULT_SECTION = "case"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run the reference 2D geology-driven case on a Gmsh planar mesh "
            "without any solver coupling."
        )
    )
    parser.add_argument(
        "--config-file",
        default=DEFAULT_CONFIG_FILE,
        help=(
            "Path to case TOML config. "
            f"Default: {DEFAULT_CONFIG_FILE} (cwd first, then script directory)."
        ),
    )
    parser.add_argument("--section", default=DEFAULT_SECTION)
    parser.add_argument("--output-figure", default=None)
    parser.add_argument("--output-summary-json", default=None)
    parser.add_argument("--no-show-plot", action="store_true")
    return parser.parse_args(argv)


def build_reference_case_state_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, Any]:
    """Resolve the 2D case and return all intermediate runtime objects."""

    config_path = resolve_reference_case_config_path(config_toml)
    cfg = resolve_reference_case_config(config_path, section=section)

    geology_field = GeologyField.from_dict(cfg["geology"])
    field_param = FieldParam.from_dict(cfg["field_param"])
    if bool(cfg["strict_field_spatial_id_match"]) and field_param.is_heterogeneous:
        required_field_id = str(getattr(field_param, "field_spatial_id", "")).strip()
        support_field_id = str(getattr(geology_field, "identifier", "")).strip()
        if required_field_id and support_field_id and required_field_id != support_field_id:
            raise ValueError(
                "field_param.field_spatial_id does not match geology identifier: "
                f"{required_field_id!r} != {support_field_id!r}"
            )

    mesh = build_reference_mesh_from_toml(config_path, section=section)
    n_sub = int(
        cfg["cell_samples_per_axis"] or getattr(geology_field, "default_cell_samples_per_axis", 8)
    )
    field_discretization = geology_field.on_mesh(mesh, cell_samples_per_axis=n_sub)
    mesh_values = field_param.to_mesh_field(field_discretization, depth=float(cfg["depth"]))
    summary = build_reference_case_summary(
        mesh=mesh,
        geology_field=geology_field,
        field_param=field_param,
        field_discretization=field_discretization,
        mesh_values=mesh_values,
    )
    return {
        "config_path": config_path,
        "config": cfg,
        "geology_field": geology_field,
        "field_param": field_param,
        "mesh": mesh,
        "field_discretization": field_discretization,
        "mesh_values": mesh_values,
        "summary": summary,
    }


def run_reference_case_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
    output_figure: str | Path | None = None,
    output_summary_json: str | Path | None = None,
    show_plot: bool = False,
) -> dict[str, Any]:
    """Run the reference 2D case and return the stable summary payload."""

    state = build_reference_case_state_from_toml(config_toml, section=section)
    config_path = Path(state["config_path"])
    cfg = dict(state["config"])
    geology_field = state["geology_field"]
    mesh = state["mesh"]
    field_discretization = state["field_discretization"]
    mesh_values = state["mesh_values"]

    figure_path = optional_case_output_path(
        config_path,
        config_value=cfg["output_figure"],
        override_value=output_figure,
    )
    summary_path = optional_case_output_path(
        config_path,
        config_value=cfg["output_summary_json"],
        override_value=output_summary_json,
    )
    summary = dict(state["summary"])

    fig = None
    if figure_path is not None or show_plot:
        if show_plot:
            ensure_interactive_backend_for_show()
        fig = build_reference_case_figure(
            cfg=cfg,
            geology_field=geology_field,
            mesh=mesh,
            field_discretization=field_discretization,
            mesh_values=mesh_values,
        )
        if figure_path is not None:
            fig.savefig(figure_path)
            summary["output_figure"] = str(figure_path)

    if summary_path is not None:
        write_case_json(summary_path, summary)
        summary["output_summary_json"] = str(summary_path)

    if show_plot:
        show_figures_blocking(fig)
    elif fig is not None:
        plt.close(fig)
    return summary


def main(argv=None) -> int:
    args = _parse_args(argv)
    summary = run_reference_case_from_toml(
        args.config_file,
        section=args.section,
        output_figure=args.output_figure,
        output_summary_json=args.output_summary_json,
        show_plot=(not bool(args.no_show_plot)),
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


__all__ = [
    "DEFAULT_CONFIG_FILE",
    "DEFAULT_SECTION",
    "GmshPlanarMesh2D",
    "build_reference_case_state_from_toml",
    "build_reference_mesh_from_toml",
    "main",
    "run_reference_case_from_toml",
]


if __name__ == "__main__":
    raise SystemExit(main())
