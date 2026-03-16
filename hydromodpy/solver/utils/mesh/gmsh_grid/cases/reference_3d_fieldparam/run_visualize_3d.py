"""Build lightweight QA figures from the postprocessed 3D reference outputs.

This script is the non-interactive visual companion to the 3D reference case.
It creates layer maps and vertical profiles from already attached 3D prism
values, which makes it useful for quick review and non-regression outputs
without requiring a 3D viewer.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import tomllib
from typing import Any

from matplotlib import pyplot as plt

from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_3d_fieldparam.run_postprocess_3d import (
    build_reference_3d_postprocess_state_from_toml,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.extruded_mesh_visualization import (
    build_layer_maps_figure,
    build_source_cell_marker_specs,
    build_vertical_profiles_figure,
    build_visualization_summary,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.plotting_utils import (
    ensure_interactive_backend_for_show,
    show_figures_blocking,
)

plt.switch_backend("Agg")


DEFAULT_CONFIG_FILE = "case_visualization_3d.toml"
DEFAULT_SECTION = "case"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Build lightweight layer/profile figures from the 3D postprocessed reference case."
    )
    parser.add_argument("--config-file", default=DEFAULT_CONFIG_FILE)
    parser.add_argument("--section", default=DEFAULT_SECTION)
    parser.add_argument("--output-summary-json", default=None)
    parser.add_argument("--output-layers-png", default=None)
    parser.add_argument("--output-profiles-png", default=None)
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


def _resolve_relative_path(raw_path: str | Path, *, base_dir: Path) -> str:
    path = Path(str(raw_path)).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return str(path)


def _resolve_optional_output_path(
    config_toml: Path, config_value: Any, override_value: str | None
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
        "reference_3d_postprocess_config": _resolve_relative_path(
            section_cfg["reference_3d_postprocess_config"],
            base_dir=config_toml.parent,
        ),
        "reference_3d_postprocess_section": str(
            section_cfg.get("reference_3d_postprocess_section", "case")
        ).strip()
        or "case",
        "output_summary_json": section_cfg.get("output_summary_json"),
        "output_layers_png": section_cfg.get("output_layers_png"),
        "output_profiles_png": section_cfg.get("output_profiles_png"),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def build_reference_3d_visualization_state_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, Any]:
    config_path = _resolve_config_path(config_toml)
    cfg = _resolve_case_config(config_path, section=section)
    postprocess_state = build_reference_3d_postprocess_state_from_toml(
        cfg["reference_3d_postprocess_config"],
        section=str(cfg["reference_3d_postprocess_section"]),
    )
    mesh_with_values = postprocess_state["mesh_with_values"]
    marker_specs = build_source_cell_marker_specs(mesh_with_values)
    summary = build_visualization_summary(mesh_with_values, marker_specs=marker_specs)
    return {
        "config_path": config_path,
        "config": cfg,
        "postprocess_state": postprocess_state,
        "mesh_with_values": mesh_with_values,
        "marker_specs": marker_specs,
        "summary": summary,
    }


def run_reference_3d_visualization_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
    output_summary_json: str | Path | None = None,
    output_layers_png: str | Path | None = None,
    output_profiles_png: str | Path | None = None,
    show_plot: bool = False,
) -> dict[str, Any]:
    state = build_reference_3d_visualization_state_from_toml(
        config_toml, section=section
    )
    config_path = Path(state["config_path"])
    cfg = dict(state["config"])
    mesh_with_values = state["mesh_with_values"]
    marker_specs = list(state["marker_specs"])
    summary = dict(state["summary"])

    summary_path = _resolve_optional_output_path(
        config_path,
        cfg.get("output_summary_json"),
        None if output_summary_json is None else str(output_summary_json),
    )
    layers_path = _resolve_optional_output_path(
        config_path,
        cfg.get("output_layers_png"),
        None if output_layers_png is None else str(output_layers_png),
    )
    profiles_path = _resolve_optional_output_path(
        config_path,
        cfg.get("output_profiles_png"),
        None if output_profiles_png is None else str(output_profiles_png),
    )
    if show_plot:
        ensure_interactive_backend_for_show()

    layers_fig = build_layer_maps_figure(
        mesh_with_values,
        marker_specs=marker_specs,
        title="Reference 3D layers on the extruded prism mesh",
    )
    profiles_fig = build_vertical_profiles_figure(
        mesh_with_values,
        marker_specs=marker_specs,
        title="Reference 3D vertical profiles",
    )

    if summary_path is not None:
        _write_json(summary_path, summary)
        summary["output_summary_json"] = str(summary_path)
    if layers_path is not None:
        layers_fig.savefig(layers_path)
        summary["output_layers_png"] = str(layers_path)
    if profiles_path is not None:
        profiles_fig.savefig(profiles_path)
        summary["output_profiles_png"] = str(profiles_path)

    if show_plot:
        show_figures_blocking(layers_fig, profiles_fig)
    else:
        from matplotlib import pyplot as plt

        plt.close(layers_fig)
        plt.close(profiles_fig)
    return summary


def main(argv=None) -> int:
    args = _parse_args(argv)
    summary = run_reference_3d_visualization_from_toml(
        args.config_file,
        section=args.section,
        output_summary_json=args.output_summary_json,
        output_layers_png=args.output_layers_png,
        output_profiles_png=args.output_profiles_png,
        show_plot=bool(args.show_plot),
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
