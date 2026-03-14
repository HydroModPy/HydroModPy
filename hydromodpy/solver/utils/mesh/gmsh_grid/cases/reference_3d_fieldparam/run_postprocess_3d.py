"""Reference 3D postprocessing/export runner on the extruded prism mesh."""

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

from hydromodpy.solver.utils.mesh.gmsh_grid import attach_extruded_values
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_3d_fieldparam.run_case_3d_fieldparam import (
    build_reference_3d_fieldparam_state_from_toml,
)


DEFAULT_CONFIG_FILE = "case_postprocess_3d.toml"
DEFAULT_SECTION = "case"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Attach, inspect and export 3D values on the reference prism mesh."
    )
    parser.add_argument("--config-file", default=DEFAULT_CONFIG_FILE)
    parser.add_argument("--section", default=DEFAULT_SECTION)
    parser.add_argument("--output-summary-json", default=None)
    parser.add_argument("--output-values-npy", default=None)
    parser.add_argument("--output-vtu", default=None)
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
    return {
        "reference_3d_fieldparam_config": _resolve_relative_path(
            section_cfg["reference_3d_fieldparam_config"],
            base_dir=config_toml.parent,
        ),
        "reference_3d_fieldparam_section": str(
            section_cfg.get("reference_3d_fieldparam_section", "case")
        ).strip()
        or "case",
        "label": str(section_cfg.get("label", "field_param_value")).strip() or "field_param_value",
        "value_name": str(section_cfg.get("value_name", "field_param_value")).strip() or "field_param_value",
        "depth_name": str(section_cfg.get("depth_name", "prism_center_depth")).strip() or "prism_center_depth",
        "output_summary_json": section_cfg.get("output_summary_json"),
        "output_values_npy": section_cfg.get("output_values_npy"),
        "output_vtu": section_cfg.get("output_vtu"),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _build_summary(*, mesh_with_values, state_3d_fieldparam, value_name: str) -> dict[str, Any]:
    n_layers = int(mesh_with_values.n_layers)
    n_cells_2d = int(mesh_with_values.n_cells_2d)
    center_source = int(n_cells_2d // 2)
    layer_zero = mesh_with_values.extract_layer(0, label=f"{value_name}_layer_0")
    center_profile = mesh_with_values.extract_vertical_profile(center_source)

    summary = mesh_with_values.to_summary_dict()
    summary.update(
        {
            "field_id": str(getattr(state_3d_fieldparam["geology_field"], "identifier", "")),
            "field_param_id": str(getattr(state_3d_fieldparam["field_param"], "identifier", "")),
            "field_param_kind": str(getattr(state_3d_fieldparam["field_param"], "kind", "")),
            "layer0_signature_head": [
                round(float(v), 12) for v in np.asarray(layer_zero.cell_values, dtype=float).reshape(-1)[:8]
            ],
            "center_profile": [round(float(v), 12) for v in center_profile["values"]],
            "center_depth_profile": [
                round(float(v), 12) for v in center_profile.get("depths", [])
            ],
            "layer_mean_sequence": [
                round(float(layer_stats["mean"]), 12) for layer_stats in mesh_with_values.layer_stats()
            ],
        }
    )
    return summary


def build_reference_3d_postprocess_state_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, Any]:
    config_path = _resolve_config_path(config_toml)
    cfg = _resolve_case_config(config_path, section=section)
    state_3d_fieldparam = build_reference_3d_fieldparam_state_from_toml(
        cfg["reference_3d_fieldparam_config"],
        section=str(cfg["reference_3d_fieldparam_section"]),
    )
    result = state_3d_fieldparam["result"]
    mesh_with_values = attach_extruded_values(
        state_3d_fieldparam["mesh_3d"],
        result.values_3d,
        label=str(cfg["label"]),
        prism_center_depths=result.prism_center_depths,
        metadata={
            "field_id": str(getattr(state_3d_fieldparam["geology_field"], "identifier", "")),
            "field_param_id": str(getattr(state_3d_fieldparam["field_param"], "identifier", "")),
        },
    )
    summary = _build_summary(
        mesh_with_values=mesh_with_values,
        state_3d_fieldparam=state_3d_fieldparam,
        value_name=str(cfg["value_name"]),
    )
    return {
        "config_path": config_path,
        "config": cfg,
        "state_3d_fieldparam": state_3d_fieldparam,
        "mesh_with_values": mesh_with_values,
        "summary": summary,
    }


def run_reference_3d_postprocess_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
    output_summary_json: str | Path | None = None,
    output_values_npy: str | Path | None = None,
    output_vtu: str | Path | None = None,
) -> dict[str, Any]:
    state = build_reference_3d_postprocess_state_from_toml(config_toml, section=section)
    config_path = Path(state["config_path"])
    cfg = dict(state["config"])
    mesh_with_values = state["mesh_with_values"]
    summary = dict(state["summary"])

    summary_path = _resolve_optional_output_path(
        config_path,
        cfg.get("output_summary_json"),
        None if output_summary_json is None else str(output_summary_json),
    )
    values_path = _resolve_optional_output_path(
        config_path,
        cfg.get("output_values_npy"),
        None if output_values_npy is None else str(output_values_npy),
    )
    vtu_path = _resolve_optional_output_path(
        config_path,
        cfg.get("output_vtu"),
        None if output_vtu is None else str(output_vtu),
    )

    if summary_path is not None:
        _write_json(summary_path, summary)
        summary["output_summary_json"] = str(summary_path)
    if values_path is not None:
        mesh_with_values.to_npy(values_path)
        summary["output_values_npy"] = str(values_path)
    if vtu_path is not None:
        try:
            mesh_with_values.to_file(
                vtu_path,
                value_name=str(cfg["value_name"]),
                depth_name=str(cfg["depth_name"]),
            )
        except ImportError:
            summary["output_vtu_status"] = "skipped_meshio_missing"
        else:
            summary["output_vtu"] = str(vtu_path)
            summary["output_vtu_status"] = "written"
    return summary


def main(argv=None) -> int:
    args = _parse_args(argv)
    summary = run_reference_3d_postprocess_from_toml(
        args.config_file,
        section=args.section,
        output_summary_json=args.output_summary_json,
        output_values_npy=args.output_values_npy,
        output_vtu=args.output_vtu,
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
