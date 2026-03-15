"""Launch the optional PyVista viewer on the reference 3D prism-value case.

This runner reuses the already discretized 3D reference workflow and opens an
interactive local inspection tool. It is intentionally thin: the mesh/value
logic stays elsewhere, and this file only handles configuration, viewer setup,
and lightweight summary outputs.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import tomllib
from typing import Any

from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_3d_fieldparam.run_postprocess_3d import (
    build_reference_3d_postprocess_state_from_toml,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.interactive_3d_viewer import (
    show_interactive_values_3d,
)

DEFAULT_CONFIG_FILE = "case_interactive_viewer.toml"
DEFAULT_SECTION = "case"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Launch the optional PyVista interactive viewer on the 3D reference case."
    )
    parser.add_argument("--config-file", default=DEFAULT_CONFIG_FILE)
    parser.add_argument("--section", default=DEFAULT_SECTION)
    parser.add_argument("--show", dest="show", action="store_true", default=None)
    parser.add_argument("--no-show", dest="show", action="store_false")
    parser.add_argument("--off-screen", action="store_true")
    parser.add_argument("--output-summary-json", default=None)
    parser.add_argument("--output-screenshot-png", default=None)
    parser.add_argument("--threshold-min", type=float, default=None)
    parser.add_argument("--threshold-max", type=float, default=None)
    parser.add_argument("--clip-normal", default=None)
    parser.add_argument("--highlight-source-cell-index", type=int, default=None)
    parser.add_argument("--highlight-prism-index", type=int, default=None)
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
        "value_name": str(section_cfg.get("value_name", "field_param_value")).strip()
        or "field_param_value",
        "depth_name": str(section_cfg.get("depth_name", "prism_center_depth")).strip()
        or "prism_center_depth",
        "cmap": str(section_cfg.get("cmap", "viridis")).strip() or "viridis",
        "show_edges": bool(section_cfg.get("show_edges", False)),
        "opacity": float(section_cfg.get("opacity", 1.0)),
        "vertical_exaggeration": float(section_cfg.get("vertical_exaggeration", 1.0)),
        "show": bool(section_cfg.get("show", True)),
        "off_screen": bool(section_cfg.get("off_screen", False)),
        "output_summary_json": section_cfg.get("output_summary_json"),
        "output_screenshot_png": section_cfg.get("output_screenshot_png"),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def build_reference_interactive_viewer_state_from_toml(
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
    return {
        "config_path": config_path,
        "config": cfg,
        "postprocess_state": postprocess_state,
        "mesh_with_values": postprocess_state["mesh_with_values"],
    }


def run_reference_interactive_viewer_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
    show: bool | None = None,
    off_screen: bool = False,
    output_summary_json: str | Path | None = None,
    output_screenshot_png: str | Path | None = None,
    threshold_range: tuple[float, float] | None = None,
    clip_normal: str | None = None,
    highlight_source_cell_index: int | None = None,
    highlight_prism_index: int | None = None,
) -> dict[str, Any]:
    state = build_reference_interactive_viewer_state_from_toml(
        config_toml, section=section
    )
    config_path = Path(state["config_path"])
    cfg = dict(state["config"])
    mesh_with_values = state["mesh_with_values"]

    summary_path = _resolve_optional_output_path(
        config_path,
        cfg.get("output_summary_json"),
        None if output_summary_json is None else str(output_summary_json),
    )
    screenshot_path = _resolve_optional_output_path(
        config_path,
        cfg.get("output_screenshot_png"),
        None if output_screenshot_png is None else str(output_screenshot_png),
    )
    do_show = bool(cfg["show"]) if show is None else bool(show)
    viewer_result = show_interactive_values_3d(
        mesh_with_values,
        value_name=str(cfg["value_name"]),
        depth_name=str(cfg["depth_name"]),
        cmap=str(cfg["cmap"]),
        show_edges=bool(cfg["show_edges"]),
        opacity=float(cfg["opacity"]),
        threshold_range=threshold_range,
        clip_normal=clip_normal,
        vertical_exaggeration=float(cfg["vertical_exaggeration"]),
        highlight_source_cell_index=highlight_source_cell_index,
        highlight_prism_index=highlight_prism_index,
        show=do_show,
        off_screen=(
            bool(off_screen)
            or screenshot_path is not None
            or not do_show
            or bool(cfg["off_screen"])
        ),
        screenshot_path=screenshot_path,
        title="Reference 3D interactive viewer",
    )
    grid = viewer_result["grid"]
    display_grid = viewer_result["display_grid"]
    summary = {
        "value_name": str(cfg["value_name"]),
        "depth_name": str(cfg["depth_name"]),
        "cmap": str(cfg["cmap"]),
        "show_edges": bool(cfg["show_edges"]),
        "opacity": float(cfg["opacity"]),
        "vertical_exaggeration": float(cfg["vertical_exaggeration"]),
        "n_cells_3d": int(grid.n_cells),
        "n_points_3d": int(grid.n_points),
        "display_n_cells": int(display_grid.n_cells),
        "display_n_points": int(display_grid.n_points),
        "cell_data_keys": sorted(str(key) for key in grid.cell_data.keys()),
        "point_data_keys": sorted(str(key) for key in grid.point_data.keys()),
        "selection": viewer_result["selection"],
        "show": bool(do_show),
        "off_screen": bool(
            off_screen
            or screenshot_path is not None
            or not do_show
            or bool(cfg["off_screen"])
        ),
    }
    if screenshot_path is not None:
        summary["output_screenshot_png"] = str(screenshot_path)
    if summary_path is not None:
        _write_json(summary_path, summary)
        summary["output_summary_json"] = str(summary_path)
    return summary


def main(argv=None) -> int:
    args = _parse_args(argv)
    threshold_range = None
    if args.threshold_min is not None and args.threshold_max is not None:
        threshold_range = (float(args.threshold_min), float(args.threshold_max))
    summary = run_reference_interactive_viewer_from_toml(
        args.config_file,
        section=args.section,
        show=args.show,
        off_screen=bool(args.off_screen),
        output_summary_json=args.output_summary_json,
        output_screenshot_png=args.output_screenshot_png,
        threshold_range=threshold_range,
        clip_normal=args.clip_normal,
        highlight_source_cell_index=args.highlight_source_cell_index,
        highlight_prism_index=args.highlight_prism_index,
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
