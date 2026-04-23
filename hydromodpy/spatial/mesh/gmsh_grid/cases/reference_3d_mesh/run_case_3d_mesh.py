"""Build the reference 3D prism mesh from the reference 2D Gmsh mesh."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from hydromodpy.spatial.mesh.gmsh_grid import ExtrudedPrismMesh3D
from hydromodpy.spatial.mesh.gmsh_grid.cases._common import (
    optional_case_output_path,
    write_case_json,
)
from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_2d_geology_base.case_config import (
    build_reference_mesh_from_toml,
)
from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_3d_mesh.case_config import (
    resolve_reference_3d_mesh_config,
    resolve_reference_3d_mesh_config_path,
)

DEFAULT_CONFIG_FILE = "case_config_3d_mesh.toml"
DEFAULT_SECTION = "case"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Extrude the 2D Gmsh reference mesh into one 3D prism mesh."
    )
    parser.add_argument("--config-file", default=DEFAULT_CONFIG_FILE)
    parser.add_argument("--section", default=DEFAULT_SECTION)
    parser.add_argument("--output-summary-json", default=None)
    parser.add_argument("--output-mesh", default=None)
    return parser.parse_args(argv)


def _build_summary(
    *,
    mesh_3d: ExtrudedPrismMesh3D,
    reference_2d_config: Path,
) -> dict[str, object]:
    return {
        "mesh_kind": str(mesh_3d.kind),
        "cell_type_2d": str(mesh_3d.cell_type_2d),
        "cell_type_3d": str(mesh_3d.cell_type_3d),
        "n_layers": int(mesh_3d.n_layers),
        "n_nodes_2d": int(mesh_3d.planar_mesh.n_nodes),
        "n_cells_2d": int(mesh_3d.planar_mesh.n_cells),
        "n_nodes_3d": int(mesh_3d.n_nodes),
        "n_cells_3d": int(mesh_3d.n_prisms),
        "bounds": [round(float(v), 6) for v in mesh_3d.bounds],
        "z_interfaces": [round(float(v), 6) for v in mesh_3d.z_interfaces],
        "layer_centers_z": [round(float(v), 6) for v in mesh_3d.layer_centers_z],
        "source_2d_case_config": reference_2d_config.name,
        "layer_index_head": [int(v) for v in mesh_3d.layer_indices[:8]],
        "source_cell_index_head": [int(v) for v in mesh_3d.source_cell_indices[:8]],
        "prism_connectivity_head": [
            [int(v) for v in row] for row in np.asarray(mesh_3d.prism_connectivity[:3], dtype=int)
        ],
    }


def build_reference_3d_mesh_state_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, object]:
    """Build the reference 3D mesh state from one case TOML."""

    config_path = resolve_reference_3d_mesh_config_path(config_toml)
    cfg = resolve_reference_3d_mesh_config(config_path, section=section)
    reference_2d_config = Path(str(cfg["reference_2d_config"])).resolve()
    planar_mesh = build_reference_mesh_from_toml(
        reference_2d_config,
        section=str(cfg["reference_2d_section"]),
    )
    mesh_3d = ExtrudedPrismMesh3D.from_layer_thicknesses(
        planar_mesh,
        top_z=float(cfg["top_z"]),
        layer_thicknesses=cfg["layer_thicknesses"],
    )
    summary = _build_summary(mesh_3d=mesh_3d, reference_2d_config=reference_2d_config)
    return {
        "config_path": config_path,
        "config": cfg,
        "reference_2d_config": reference_2d_config,
        "planar_mesh": planar_mesh,
        "mesh_3d": mesh_3d,
        "summary": summary,
    }


def run_reference_3d_mesh_case_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
    output_summary_json: str | Path | None = None,
    output_mesh: str | Path | None = None,
) -> dict[str, object]:
    """Run the reference 3D prism-mesh case."""

    state = build_reference_3d_mesh_state_from_toml(config_toml, section=section)
    config_path = Path(state["config_path"])
    cfg = dict(state["config"])
    mesh_3d = state["mesh_3d"]
    summary = dict(state["summary"])

    summary_path = optional_case_output_path(
        config_path,
        config_value=cfg.get("output_summary_json"),
        override_value=output_summary_json,
    )
    mesh_path = optional_case_output_path(
        config_path,
        config_value=None,
        override_value=output_mesh,
    )

    if summary_path is not None:
        write_case_json(summary_path, summary)
        summary["output_summary_json"] = str(summary_path)
    if mesh_path is not None:
        mesh_3d.to_file(mesh_path)
        summary["output_mesh"] = str(mesh_path)
    return summary


def main(argv=None) -> int:
    args = _parse_args(argv)
    summary = run_reference_3d_mesh_case_from_toml(
        args.config_file,
        section=args.section,
        output_summary_json=args.output_summary_json,
        output_mesh=args.output_mesh,
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


__all__ = [
    "DEFAULT_CONFIG_FILE",
    "DEFAULT_SECTION",
    "build_reference_3d_mesh_state_from_toml",
    "main",
    "run_reference_3d_mesh_case_from_toml",
]


if __name__ == "__main__":
    raise SystemExit(main())
