"""Reference 3D FieldParam discretization case on an extruded prism mesh."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import sys
import tomllib
from typing import Any

import matplotlib
import numpy as np


def _configure_matplotlib_backend_from_argv(argv: list[str]) -> None:
    if "--show-plot" not in argv:
        return
    backend = str(matplotlib.get_backend()).strip().lower()
    if ("inline" not in backend) and ("agg" not in backend):
        return
    for candidate in ("TkAgg", "QtAgg"):
        try:
            matplotlib.use(candidate, force=True)
            return
        except Exception:
            continue


_configure_matplotlib_backend_from_argv(sys.argv[1:])

from matplotlib import pyplot as plt


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "hydromodpy").is_dir():
            return parent
    return current.parents[0]


REPO_ROOT = _find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.field.core.field_param import FieldParam
from hydromodpy.solver.utils.mesh.gmsh_grid import (
    attach_extruded_values,
    discretize_fieldparam_on_extruded_mesh,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_base.run_case_gmsh import (
    _disable_axis_offset,
    _maybe_scientific_colorbar,
    _show_figures_blocking,
    build_reference_case_state_from_toml,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_3d_mesh.run_case_3d_mesh import (
    build_reference_3d_mesh_state_from_toml,
)


DEFAULT_CONFIG_FILE = "case_config_3d_fieldparam.toml"
DEFAULT_SECTION = "case"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Discretize one FieldParam on the 3D extruded prism reference mesh."
    )
    parser.add_argument("--config-file", default=DEFAULT_CONFIG_FILE)
    parser.add_argument("--section", default=DEFAULT_SECTION)
    parser.add_argument("--output-summary-json", default=None)
    parser.add_argument("--output-values-npy", default=None)
    parser.add_argument("--output-overview-png", default=None)
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


def _get_nested_section(payload: Mapping[str, Any], dotted_path: str) -> Mapping[str, Any]:
    current: Any = payload
    for token in str(dotted_path).split("."):
        if not isinstance(current, Mapping) or token not in current:
            raise KeyError(f"Missing TOML section '{dotted_path}'")
        current = current[token]
    if not isinstance(current, Mapping):
        raise ValueError(f"TOML section '{dotted_path}' must be a mapping")
    return current


def _optional_nested_section(payload: Mapping[str, Any], dotted_path: str) -> Mapping[str, Any] | None:
    try:
        return _get_nested_section(payload, dotted_path)
    except (KeyError, ValueError):
        return None


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


def _array_stats(arr) -> dict[str, float]:
    values = np.asarray(arr, dtype=float)
    finite = values[np.isfinite(values)]
    return {
        "min": round(float(np.min(finite)), 12),
        "max": round(float(np.max(finite)), 12),
        "mean": round(float(np.mean(finite)), 12),
        "sum": round(float(np.sum(finite)), 12),
    }


def _resolve_case_config(config_toml: Path, *, section: str = "case") -> dict[str, Any]:
    payload = tomllib.loads(config_toml.read_text(encoding="utf-8-sig"))
    section_cfg = dict(_get_nested_section(payload, section))
    vertical_override = _optional_nested_section(payload, f"{section}.field_param_vertical_profile")

    return {
        "reference_2d_config": _resolve_relative_path(section_cfg["reference_2d_config"], base_dir=config_toml.parent),
        "reference_2d_section": str(section_cfg.get("reference_2d_section", "case")).strip() or "case",
        "reference_3d_mesh_config": _resolve_relative_path(
            section_cfg["reference_3d_mesh_config"],
            base_dir=config_toml.parent,
        ),
        "reference_3d_mesh_section": str(section_cfg.get("reference_3d_mesh_section", "case")).strip() or "case",
        "depth": float(section_cfg.get("depth", 0.0)),
        "cell_samples_per_axis": (
            None
            if section_cfg.get("cell_samples_per_axis") is None
            else max(2, int(section_cfg["cell_samples_per_axis"]))
        ),
        "strict_field_spatial_id_match": bool(section_cfg.get("strict_field_spatial_id_match", True)),
        "output_summary_json": section_cfg.get("output_summary_json"),
        "output_values_npy": section_cfg.get("output_values_npy"),
        "output_overview_png": section_cfg.get("output_overview_png"),
        "field_param_vertical_profile": None if vertical_override is None else dict(vertical_override),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _override_field_param_vertical_profile(field_param: FieldParam, vertical_profile: Mapping[str, Any] | None) -> FieldParam:
    if vertical_profile is None:
        return field_param
    payload = field_param.as_dict()
    payload["vertical_profile"] = dict(vertical_profile)
    return FieldParam.from_dict(payload)


def _build_summary(*, result, geology_field, field_param) -> dict[str, Any]:
    values_2d = np.asarray(result.values_2d, dtype=float)
    values_3d = np.asarray(result.values_3d, dtype=float)
    depth_3d = np.asarray(result.prism_center_depths, dtype=float)
    n_layers, n_cells_2d = values_3d.shape
    center_source = int(n_cells_2d // 2)

    return {
        "mesh_kind": str(result.mesh_3d.kind),
        "cell_type_2d": str(result.mesh_3d.cell_type_2d),
        "cell_type_3d": str(result.mesh_3d.cell_type_3d),
        "field_id": str(getattr(geology_field, "identifier", "")),
        "field_param_id": str(getattr(field_param, "identifier", "")),
        "field_param_kind": str(getattr(field_param, "kind", "")),
        "shape_2d": [int(v) for v in values_2d.shape],
        "shape_3d": [int(v) for v in values_3d.shape],
        "n_layers": int(n_layers),
        "n_cells_2d": int(n_cells_2d),
        "n_cells_3d": int(result.mesh_3d.n_prisms),
        "stats_2d": _array_stats(values_2d),
        "stats_3d": _array_stats(values_3d),
        "depth_stats": _array_stats(depth_3d),
        "layer_means": [round(float(np.mean(values_3d[ilay])), 12) for ilay in range(n_layers)],
        "layer_depth_means": [round(float(np.mean(depth_3d[ilay])), 12) for ilay in range(n_layers)],
        "center_profile": [round(float(v), 12) for v in values_3d[:, center_source]],
        "center_depth_profile": [round(float(v), 12) for v in depth_3d[:, center_source]],
        "surface_signature_head": [round(float(v), 12) for v in values_2d[:8]],
        "values_3d_signature_head": [round(float(v), 12) for v in values_3d.reshape(-1)[:8]],
    }


def _selected_layer_indices(n_layers: int) -> list[int]:
    if n_layers <= 0:
        return []
    candidates = [0, n_layers // 2, n_layers - 1]
    selected: list[int] = []
    for idx in candidates:
        idx_int = int(idx)
        if idx_int not in selected:
            selected.append(idx_int)
    return selected


def _plot_layer_panel(
    ax,
    *,
    mesh,
    layer_values,
    layer_index: int,
    layer_depth: float,
    vmin: float,
    vmax: float,
):
    mappable = mesh.plot_cell_values(
        ax,
        layer_values,
        cmap="viridis",
        show_mesh=True,
        vmin=vmin,
        vmax=vmax,
    )
    ax.set_title(f"Layer {layer_index + 1}\nmean depth = {layer_depth:.1f} m", fontsize=18)
    ax.set_xlabel("x [m]", fontsize=14)
    ax.set_ylabel("y [m]", fontsize=14)
    ax.tick_params(labelsize=12)
    ax.set_aspect("equal")
    _disable_axis_offset(ax)
    return mappable


def _draw_summary_boxes(ax, *, summary: Mapping[str, Any]) -> None:
    blocks = [
        ("FieldParam", str(summary["field_param_id"])),
        ("Layers", str(summary["n_layers"])),
        ("Cells 2D", str(summary["n_cells_2d"])),
        ("Cells 3D", str(summary["n_cells_3d"])),
        (
            "Min / Max",
            f"{float(summary['stats_3d']['min']):.3e}\n{float(summary['stats_3d']['max']):.3e}",
        ),
        (
            "Mean / Sum",
            f"{float(summary['stats_3d']['mean']):.3e}\n{float(summary['stats_3d']['sum']):.3e}",
        ),
    ]
    n_cols = 2
    for idx, (label, value) in enumerate(blocks):
        row = idx // n_cols
        col = idx % n_cols
        x = 0.03 + col * 0.48
        y = 0.88 - row * 0.31
        ax.text(
            x,
            y,
            f"{label}\n{value}",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=15,
            weight="bold",
            color="0.10",
            bbox={
                "boxstyle": "round,pad=0.55",
                "fc": "#f7f7f7",
                "ec": "#c9c9c9",
                "lw": 1.0,
            },
        )


def _build_reference_3d_fieldparam_figure(
    *,
    mesh_with_values,
    summary: Mapping[str, Any],
):
    planar_mesh = mesh_with_values.mesh.planar_mesh
    values_3d = np.asarray(mesh_with_values.values_3d, dtype=float)
    depth_3d = np.asarray(mesh_with_values.prism_center_depths, dtype=float)
    selected_layers = _selected_layer_indices(int(mesh_with_values.n_layers))
    flat_values = np.asarray(values_3d, dtype=float).reshape(-1)
    vmin = float(np.nanmin(flat_values))
    vmax = float(np.nanmax(flat_values))

    fig = plt.figure(figsize=(24.0, 12.5), dpi=160)
    axes = fig.subplot_mosaic(
        [
            ["layer0", "layer1", "layer2", "cbar"],
            ["profile", "means", "summary", "cbar"],
        ],
        width_ratios=[1.0, 1.0, 1.0, 0.05],
        height_ratios=[1.0, 0.78],
    )

    layer_axes = [axes["layer0"], axes["layer1"], axes["layer2"]]
    mappable = None
    for axis_idx, ax in enumerate(layer_axes):
        if axis_idx >= len(selected_layers):
            ax.axis("off")
            continue
        layer_index = int(selected_layers[axis_idx])
        mappable = _plot_layer_panel(
            ax,
            mesh=planar_mesh,
            layer_values=values_3d[layer_index, :],
            layer_index=layer_index,
            layer_depth=float(np.mean(depth_3d[layer_index, :])),
            vmin=vmin,
            vmax=vmax,
        )

    ax_cbar = axes["cbar"]
    cbar = fig.colorbar(mappable, cax=ax_cbar, orientation="vertical")
    cbar.set_label("Field parameter value", fontsize=14, rotation=90, labelpad=14)
    cbar.ax.tick_params(labelsize=12)
    _maybe_scientific_colorbar(cbar, flat_values)

    center_source = int(mesh_with_values.n_cells_2d // 2)
    center_profile = mesh_with_values.extract_vertical_profile(center_source)
    ax_profile = axes["profile"]
    ax_profile.plot(
        np.asarray(center_profile["values"], dtype=float),
        np.asarray(center_profile.get("depths", []), dtype=float),
        marker="o",
        color="#0f766e",
        lw=2.2,
        ms=7.0,
    )
    ax_profile.set_title("Center vertical profile", fontsize=18)
    ax_profile.set_xlabel("Field parameter value", fontsize=14)
    ax_profile.set_ylabel("Depth [m]", fontsize=14)
    ax_profile.tick_params(labelsize=12)
    ax_profile.grid(True, color="0.88", lw=0.8)
    ax_profile.invert_yaxis()

    layer_stats = mesh_with_values.layer_stats()
    layer_depths = np.asarray(summary["layer_depth_means"], dtype=float)
    layer_means = np.asarray([layer["mean"] for layer in layer_stats], dtype=float)
    layer_mins = np.asarray([layer["min"] for layer in layer_stats], dtype=float)
    layer_maxs = np.asarray([layer["max"] for layer in layer_stats], dtype=float)
    ax_means = axes["means"]
    ax_means.fill_betweenx(layer_depths, layer_mins, layer_maxs, color="#93c5fd", alpha=0.35)
    ax_means.plot(layer_means, layer_depths, marker="o", color="#1d4ed8", lw=2.2, ms=7.0)
    ax_means.set_title("Layer mean with min/max envelope", fontsize=18)
    ax_means.set_xlabel("Field parameter value", fontsize=14)
    ax_means.set_ylabel("Depth [m]", fontsize=14)
    ax_means.tick_params(labelsize=12)
    ax_means.grid(True, color="0.88", lw=0.8)
    ax_means.invert_yaxis()

    ax_summary = axes["summary"]
    ax_summary.axis("off")
    _draw_summary_boxes(ax_summary, summary=summary)

    fig.suptitle(
        "Reference 3D FieldParam discretization overview",
        fontsize=22,
    )
    fig.subplots_adjust(left=0.05, right=0.985, top=0.92, bottom=0.07, wspace=0.22, hspace=0.24)
    return fig


def build_reference_3d_fieldparam_state_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, Any]:
    config_path = _resolve_config_path(config_toml)
    cfg = _resolve_case_config(config_path, section=section)

    state_2d = build_reference_case_state_from_toml(
        cfg["reference_2d_config"],
        section=str(cfg["reference_2d_section"]),
    )
    state_3d_mesh = build_reference_3d_mesh_state_from_toml(
        cfg["reference_3d_mesh_config"],
        section=str(cfg["reference_3d_mesh_section"]),
    )

    geology_field = state_2d["geology_field"]
    field_param = _override_field_param_vertical_profile(
        state_2d["field_param"],
        cfg["field_param_vertical_profile"],
    )
    result = discretize_fieldparam_on_extruded_mesh(
        support_field=geology_field,
        field_param=field_param,
        mesh_3d=state_3d_mesh["mesh_3d"],
        cell_samples_per_axis=cfg["cell_samples_per_axis"],
        depth=float(cfg["depth"]),
        strict_field_spatial_id_match=bool(cfg["strict_field_spatial_id_match"]),
    )
    mesh_with_values = attach_extruded_values(
        state_3d_mesh["mesh_3d"],
        result.values_3d,
        label=str(getattr(field_param, "identifier", "field_param_value")),
        prism_center_depths=result.prism_center_depths,
        metadata={
            "field_id": str(getattr(geology_field, "identifier", "")),
            "field_param_id": str(getattr(field_param, "identifier", "")),
        },
    )
    summary = _build_summary(result=result, geology_field=geology_field, field_param=field_param)
    return {
        "config_path": config_path,
        "config": cfg,
        "geology_field": geology_field,
        "field_param": field_param,
        "mesh_3d": state_3d_mesh["mesh_3d"],
        "mesh_with_values": mesh_with_values,
        "result": result,
        "summary": summary,
    }


def run_reference_3d_fieldparam_case_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
    output_summary_json: str | Path | None = None,
    output_values_npy: str | Path | None = None,
    output_overview_png: str | Path | None = None,
    show_plot: bool = False,
) -> dict[str, Any]:
    state = build_reference_3d_fieldparam_state_from_toml(config_toml, section=section)
    config_path = Path(state["config_path"])
    cfg = dict(state["config"])
    mesh_with_values = state["mesh_with_values"]
    result = state["result"]
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
    overview_path = _resolve_optional_output_path(
        config_path,
        cfg.get("output_overview_png"),
        None if output_overview_png is None else str(output_overview_png),
    )

    if summary_path is not None:
        _write_json(summary_path, summary)
        summary["output_summary_json"] = str(summary_path)
    if values_path is not None:
        np.save(values_path, np.asarray(result.values_3d, dtype=float))
        summary["output_values_npy"] = str(values_path)
    if overview_path is not None or show_plot:
        fig = _build_reference_3d_fieldparam_figure(
            mesh_with_values=mesh_with_values,
            summary=summary,
        )
        if overview_path is not None:
            fig.savefig(overview_path)
            summary["output_overview_png"] = str(overview_path)
        if show_plot:
            _show_figures_blocking(fig)
        else:
            plt.close(fig)
    return summary


def main(argv=None) -> int:
    args = _parse_args(argv)
    summary = run_reference_3d_fieldparam_case_from_toml(
        args.config_file,
        section=args.section,
        output_summary_json=args.output_summary_json,
        output_values_npy=args.output_values_npy,
        output_overview_png=args.output_overview_png,
        show_plot=bool(args.show_plot),
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
