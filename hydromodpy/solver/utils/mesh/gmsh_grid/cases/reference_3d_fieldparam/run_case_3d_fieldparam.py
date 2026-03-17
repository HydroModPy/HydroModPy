"""Run the reference 3D FieldParam discretization on an extruded prism mesh.

This case builds on the 2D reference case and the 3D extrusion case. It reuses
the planar geology support, creates the prism mesh, evaluates the FieldParam at
prism-center depths, and writes compact outputs that are easy to inspect.

It is the clearest example of how the 2D Gmsh workflow extends into 3D without
introducing a full groundwater solver.

Companion tools (postprocess, visualize, interactive) are available as
subcommands.  Run with ``--help`` for the full list.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import tomllib
from typing import Any

from matplotlib import pyplot as plt
import numpy as np

from hydromodpy.solver.utils._config_helpers import get_nested_section, resolve_path
from hydromodpy.field.core.field_param import FieldParam
from hydromodpy.solver.utils.mesh.gmsh_grid import (
    attach_extruded_values,
    discretize_fieldparam_on_extruded_mesh,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_base.run_case_gmsh import (
    build_reference_case_state_from_toml,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_3d_mesh.run_case_3d_mesh import (
    build_reference_3d_mesh_state_from_toml,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.extruded_mesh_visualization import (
    build_layer_maps_figure,
    build_source_cell_marker_specs,
    build_vertical_profiles_figure,
    build_visualization_summary,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.interactive_3d_viewer import (
    show_interactive_values_3d,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.plotting_utils import (
    disable_axis_offset,
    ensure_interactive_backend_for_show,
    maybe_scientific_colorbar,
    show_figures_blocking,
)

plt.switch_backend("Agg")


DEFAULT_CONFIG_FILE = "case_config_3d_fieldparam.toml"
DEFAULT_SECTION = "case"

# -- Postprocess defaults ----------------------------------------------------
_POSTPROCESS_DEFAULT_CONFIG_FILE = "case_postprocess_3d.toml"

# -- Visualization defaults ---------------------------------------------------
_VISUALIZATION_DEFAULT_CONFIG_FILE = "case_visualization_3d.toml"

# -- Interactive viewer defaults ----------------------------------------------
_INTERACTIVE_DEFAULT_CONFIG_FILE = "case_interactive_viewer.toml"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Reference 3D FieldParam discretization case and companion tools."
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- "run" subcommand (default) -----------------------------------------
    run_parser = subparsers.add_parser(
        "run",
        help="Run the 3D fieldparam case.",
    )
    run_parser.add_argument("--config-file", default=DEFAULT_CONFIG_FILE)
    run_parser.add_argument("--section", default=DEFAULT_SECTION)
    run_parser.add_argument("--output-summary-json", default=None)
    run_parser.add_argument("--output-values-npy", default=None)
    run_parser.add_argument("--output-overview-png", default=None)
    run_parser.add_argument("--show-plot", action="store_true")

    # --- "postprocess" subcommand -------------------------------------------
    pp_parser = subparsers.add_parser(
        "postprocess",
        help="Postprocess and export 3D values.",
    )
    pp_parser.add_argument(
        "--config-file", default=_POSTPROCESS_DEFAULT_CONFIG_FILE
    )
    pp_parser.add_argument("--section", default=DEFAULT_SECTION)
    pp_parser.add_argument("--output-summary-json", default=None)
    pp_parser.add_argument("--output-values-npy", default=None)
    pp_parser.add_argument("--output-vtu", default=None)

    # --- "visualize" subcommand ---------------------------------------------
    viz_parser = subparsers.add_parser(
        "visualize",
        help="Build QA figures.",
    )
    viz_parser.add_argument(
        "--config-file", default=_VISUALIZATION_DEFAULT_CONFIG_FILE
    )
    viz_parser.add_argument("--section", default=DEFAULT_SECTION)
    viz_parser.add_argument("--output-summary-json", default=None)
    viz_parser.add_argument("--output-layers-png", default=None)
    viz_parser.add_argument("--output-profiles-png", default=None)
    viz_parser.add_argument("--show-plot", action="store_true")

    # --- "interactive" subcommand -------------------------------------------
    int_parser = subparsers.add_parser(
        "interactive",
        help="Launch PyVista 3D viewer.",
    )
    int_parser.add_argument(
        "--config-file", default=_INTERACTIVE_DEFAULT_CONFIG_FILE
    )
    int_parser.add_argument("--section", default=DEFAULT_SECTION)
    int_parser.add_argument(
        "--show", dest="show", action="store_true", default=None
    )
    int_parser.add_argument("--no-show", dest="show", action="store_false")
    int_parser.add_argument("--off-screen", action="store_true")
    int_parser.add_argument("--output-summary-json", default=None)
    int_parser.add_argument("--output-screenshot-png", default=None)
    int_parser.add_argument("--threshold-min", type=float, default=None)
    int_parser.add_argument("--threshold-max", type=float, default=None)
    int_parser.add_argument("--clip-normal", default=None)
    int_parser.add_argument(
        "--highlight-source-cell-index", type=int, default=None
    )
    int_parser.add_argument("--highlight-prism-index", type=int, default=None)

    args = parser.parse_args(argv)
    if args.command is None:
        args.command = "run"
        # Backfill defaults expected by the "run" handler when no subcommand
        # was given and therefore no sub-parser ran.
        for attr, default in (
            ("config_file", DEFAULT_CONFIG_FILE),
            ("section", DEFAULT_SECTION),
            ("output_summary_json", None),
            ("output_values_npy", None),
            ("output_overview_png", None),
            ("show_plot", False),
        ):
            if not hasattr(args, attr):
                setattr(args, attr, default)
    return args


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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


def _optional_nested_section(
    payload: Mapping[str, Any], dotted_path: str
) -> Mapping[str, Any] | None:
    try:
        return get_nested_section(payload, dotted_path)
    except (KeyError, ValueError):
        return None


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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


# ---------------------------------------------------------------------------
# "run" — 3D FieldParam discretization
# ---------------------------------------------------------------------------

def _resolve_case_config(config_toml: Path, *, section: str = "case") -> dict[str, Any]:
    payload = tomllib.loads(config_toml.read_text(encoding="utf-8-sig"))
    section_cfg = dict(get_nested_section(payload, section))
    vertical_override = _optional_nested_section(
        payload, f"{section}.field_param_vertical_profile"
    )

    return {
        "reference_2d_config": resolve_path(
            section_cfg["reference_2d_config"], base_dir=config_toml.parent
        ),
        "reference_2d_section": str(
            section_cfg.get("reference_2d_section", "case")
        ).strip()
        or "case",
        "reference_3d_mesh_config": resolve_path(
            section_cfg["reference_3d_mesh_config"],
            base_dir=config_toml.parent,
        ),
        "reference_3d_mesh_section": str(
            section_cfg.get("reference_3d_mesh_section", "case")
        ).strip()
        or "case",
        "depth": float(section_cfg.get("depth", 0.0)),
        "cell_samples_per_axis": (
            None
            if section_cfg.get("cell_samples_per_axis") is None
            else max(2, int(section_cfg["cell_samples_per_axis"]))
        ),
        "strict_field_spatial_id_match": bool(
            section_cfg.get("strict_field_spatial_id_match", True)
        ),
        "output_summary_json": section_cfg.get("output_summary_json"),
        "output_values_npy": section_cfg.get("output_values_npy"),
        "output_overview_png": section_cfg.get("output_overview_png"),
        "field_param_vertical_profile": (
            None if vertical_override is None else dict(vertical_override)
        ),
    }


def _override_field_param_vertical_profile(
    field_param: FieldParam, vertical_profile: Mapping[str, Any] | None
) -> FieldParam:
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
        "layer_means": [
            round(float(np.mean(values_3d[ilay])), 12) for ilay in range(n_layers)
        ],
        "layer_depth_means": [
            round(float(np.mean(depth_3d[ilay])), 12) for ilay in range(n_layers)
        ],
        "center_profile": [round(float(v), 12) for v in values_3d[:, center_source]],
        "center_depth_profile": [
            round(float(v), 12) for v in depth_3d[:, center_source]
        ],
        "surface_signature_head": [round(float(v), 12) for v in values_2d[:8]],
        "values_3d_signature_head": [
            round(float(v), 12) for v in values_3d.reshape(-1)[:8]
        ],
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
    ax.set_title(
        f"Layer {layer_index + 1}\nmean depth = {layer_depth:.1f} m", fontsize=18
    )
    ax.set_xlabel("x [m]", fontsize=14)
    ax.set_ylabel("y [m]", fontsize=14)
    ax.tick_params(labelsize=12)
    ax.set_aspect("equal")
    disable_axis_offset(ax)
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
    maybe_scientific_colorbar(cbar, flat_values)

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
    ax_means.fill_betweenx(
        layer_depths, layer_mins, layer_maxs, color="#93c5fd", alpha=0.35
    )
    ax_means.plot(
        layer_means, layer_depths, marker="o", color="#1d4ed8", lw=2.2, ms=7.0
    )
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
    fig.subplots_adjust(
        left=0.05, right=0.985, top=0.92, bottom=0.07, wspace=0.22, hspace=0.24
    )
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
    summary = _build_summary(
        result=result, geology_field=geology_field, field_param=field_param
    )
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
        if show_plot:
            ensure_interactive_backend_for_show()
        fig = _build_reference_3d_fieldparam_figure(
            mesh_with_values=mesh_with_values,
            summary=summary,
        )
        if overview_path is not None:
            fig.savefig(overview_path)
            summary["output_overview_png"] = str(overview_path)
        if show_plot:
            show_figures_blocking(fig)
        else:
            plt.close(fig)
    return summary


# ---------------------------------------------------------------------------
# "postprocess" — attach, inspect and export
# ---------------------------------------------------------------------------

def _resolve_postprocess_config(
    config_toml: Path, *, section: str = "case"
) -> dict[str, Any]:
    payload = tomllib.loads(config_toml.read_text(encoding="utf-8-sig"))
    section_cfg = dict(get_nested_section(payload, section))
    return {
        "reference_3d_fieldparam_config": resolve_path(
            section_cfg["reference_3d_fieldparam_config"],
            base_dir=config_toml.parent,
        ),
        "reference_3d_fieldparam_section": str(
            section_cfg.get("reference_3d_fieldparam_section", "case")
        ).strip()
        or "case",
        "label": str(section_cfg.get("label", "field_param_value")).strip()
        or "field_param_value",
        "value_name": str(section_cfg.get("value_name", "field_param_value")).strip()
        or "field_param_value",
        "depth_name": str(section_cfg.get("depth_name", "prism_center_depth")).strip()
        or "prism_center_depth",
        "output_summary_json": section_cfg.get("output_summary_json"),
        "output_values_npy": section_cfg.get("output_values_npy"),
        "output_vtu": section_cfg.get("output_vtu"),
    }


def _build_postprocess_summary(
    *, mesh_with_values, state_3d_fieldparam, value_name: str
) -> dict[str, Any]:
    n_cells_2d = int(mesh_with_values.n_cells_2d)
    center_source = int(n_cells_2d // 2)
    layer_zero = mesh_with_values.extract_layer(0, label=f"{value_name}_layer_0")
    center_profile = mesh_with_values.extract_vertical_profile(center_source)

    summary = mesh_with_values.to_summary_dict()
    summary.update(
        {
            "field_id": str(
                getattr(state_3d_fieldparam["geology_field"], "identifier", "")
            ),
            "field_param_id": str(
                getattr(state_3d_fieldparam["field_param"], "identifier", "")
            ),
            "field_param_kind": str(
                getattr(state_3d_fieldparam["field_param"], "kind", "")
            ),
            "layer0_signature_head": [
                round(float(v), 12)
                for v in np.asarray(layer_zero.cell_values, dtype=float).reshape(-1)[:8]
            ],
            "center_profile": [round(float(v), 12) for v in center_profile["values"]],
            "center_depth_profile": [
                round(float(v), 12) for v in center_profile.get("depths", [])
            ],
            "layer_mean_sequence": [
                round(float(layer_stats["mean"]), 12)
                for layer_stats in mesh_with_values.layer_stats()
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
    cfg = _resolve_postprocess_config(config_path, section=section)
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
            "field_id": str(
                getattr(state_3d_fieldparam["geology_field"], "identifier", "")
            ),
            "field_param_id": str(
                getattr(state_3d_fieldparam["field_param"], "identifier", "")
            ),
        },
    )
    summary = _build_postprocess_summary(
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


# ---------------------------------------------------------------------------
# "visualize" — lightweight QA figures
# ---------------------------------------------------------------------------

def _resolve_visualization_config(
    config_toml: Path, *, section: str = "case"
) -> dict[str, Any]:
    payload = tomllib.loads(config_toml.read_text(encoding="utf-8-sig"))
    section_cfg = dict(get_nested_section(payload, section))
    return {
        "reference_3d_postprocess_config": resolve_path(
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


def build_reference_3d_visualization_state_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, Any]:
    config_path = _resolve_config_path(config_toml)
    cfg = _resolve_visualization_config(config_path, section=section)
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


# ---------------------------------------------------------------------------
# "interactive" — PyVista 3D viewer
# ---------------------------------------------------------------------------

def _resolve_interactive_viewer_config(
    config_toml: Path, *, section: str = "case"
) -> dict[str, Any]:
    payload = tomllib.loads(config_toml.read_text(encoding="utf-8-sig"))
    section_cfg = dict(get_nested_section(payload, section))
    return {
        "reference_3d_postprocess_config": resolve_path(
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


def build_reference_interactive_viewer_state_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, Any]:
    config_path = _resolve_config_path(config_toml)
    cfg = _resolve_interactive_viewer_config(config_path, section=section)
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


# ---------------------------------------------------------------------------
# Subcommand dispatch helpers
# ---------------------------------------------------------------------------

def _main_run(args) -> int:
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


def _main_postprocess(args) -> int:
    summary = run_reference_3d_postprocess_from_toml(
        args.config_file,
        section=args.section,
        output_summary_json=args.output_summary_json,
        output_values_npy=args.output_values_npy,
        output_vtu=args.output_vtu,
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


def _main_visualize(args) -> int:
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


def _main_interactive(args) -> int:
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


def main(argv=None) -> int:
    args = _parse_args(argv)
    if args.command == "run":
        return _main_run(args)
    elif args.command == "postprocess":
        return _main_postprocess(args)
    elif args.command == "visualize":
        return _main_visualize(args)
    elif args.command == "interactive":
        return _main_interactive(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
