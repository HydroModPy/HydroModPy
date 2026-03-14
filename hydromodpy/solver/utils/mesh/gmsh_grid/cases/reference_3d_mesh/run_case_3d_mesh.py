"""Reference 3D prism extrusion case built from the 2D Gmsh reference mesh."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import sys
import tomllib
from typing import Any

import numpy as np


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "hydromodpy").is_dir():
            return parent
    return current.parents[0]


REPO_ROOT = _find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.solver.utils.mesh.gmsh_grid import ExtrudedPrismMesh3D
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_base.run_case_gmsh import (
    build_reference_mesh_from_toml,
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


def _get_nested_section(payload: Mapping[str, Any], dotted_path: str) -> Mapping[str, Any]:
    current: Any = payload
    for token in str(dotted_path).split("."):
        if not isinstance(current, Mapping) or token not in current:
            raise KeyError(f"Missing TOML section '{dotted_path}'")
        current = current[token]
    if not isinstance(current, Mapping):
        raise ValueError(f"TOML section '{dotted_path}' must be a mapping")
    return current


def _resolve_relative_path(raw_path: str | Path, *, base_dir: Path) -> str:
    path = Path(str(raw_path)).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return str(path)


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
    layer_thicknesses = np.asarray(section_cfg.get("layer_thicknesses", []), dtype=float).reshape(-1)
    if layer_thicknesses.size == 0:
        raise ValueError("layer_thicknesses cannot be empty for the 3D reference mesh case")
    return {
        "reference_2d_config": _resolve_relative_path(section_cfg["reference_2d_config"], base_dir=config_toml.parent),
        "reference_2d_section": str(section_cfg.get("reference_2d_section", "case")).strip() or "case",
        "top_z": float(section_cfg.get("top_z", 0.0)),
        "layer_thicknesses": [float(v) for v in layer_thicknesses],
        "output_summary_json": section_cfg.get("output_summary_json"),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _build_summary(
    *,
    mesh_3d: ExtrudedPrismMesh3D,
    reference_2d_config: Path,
) -> dict[str, Any]:
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
            [int(v) for v in row]
            for row in np.asarray(mesh_3d.prism_connectivity[:3], dtype=int)
        ],
    }


def build_reference_3d_mesh_state_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, Any]:
    config_path = _resolve_config_path(config_toml)
    cfg = _resolve_case_config(config_path, section=section)
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
) -> dict[str, Any]:
    state = build_reference_3d_mesh_state_from_toml(config_toml, section=section)
    config_path = Path(state["config_path"])
    cfg = dict(state["config"])
    mesh_3d = state["mesh_3d"]
    summary = dict(state["summary"])

    summary_path = _resolve_optional_output_path(
        config_path,
        cfg.get("output_summary_json"),
        None if output_summary_json is None else str(output_summary_json),
    )
    mesh_path = _resolve_optional_output_path(
        config_path,
        None,
        None if output_mesh is None else str(output_mesh),
    )

    if summary_path is not None:
        _write_json(summary_path, summary)
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


if __name__ == "__main__":
    raise SystemExit(main())
