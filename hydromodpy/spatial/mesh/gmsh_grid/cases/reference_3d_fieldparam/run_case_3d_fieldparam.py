"""Run the reference 3D FieldParam case and its companion tools.

This module intentionally remains the runnable façade for the case family:

- ``run``: discretize the FieldParam on the extruded prism mesh
- ``postprocess``: attach/export valued meshes
- ``visualize``: build lightweight QA figures
- ``interactive``: launch the PyVista-based viewer

The config parsing, summary construction, and overview figure building now live
in dedicated helpers so this file stays closer to workflow orchestration.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from matplotlib import pyplot as plt

from hydromodpy.spatial.mesh.gmsh_grid import (
    attach_extruded_values,
    discretize_fieldparam_on_extruded_mesh,
)
from hydromodpy.spatial.mesh.gmsh_grid.cases._common import (
    optional_case_output_path,
    write_case_json,
)
from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_2d_geology_base.run_case_gmsh import (
    build_reference_case_state_from_toml,
)
from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_3d_fieldparam.case_config import (
    override_field_param_vertical_profile,
    resolve_reference_3d_fieldparam_config_path,
    resolve_reference_3d_fieldparam_run_config,
    resolve_reference_3d_postprocess_config,
    resolve_reference_3d_visualization_config,
    resolve_reference_interactive_viewer_config,
)
from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_3d_fieldparam.plotting import (
    build_reference_3d_fieldparam_figure,
)
from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_3d_fieldparam.reporting import (
    build_reference_3d_fieldparam_summary,
    build_reference_3d_postprocess_summary,
    build_reference_interactive_viewer_summary,
)
from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_3d_mesh.run_case_3d_mesh import (
    build_reference_3d_mesh_state_from_toml,
)
from hydromodpy.spatial.mesh.gmsh_grid.extruded_mesh_visualization import (
    build_layer_maps_figure,
    build_source_cell_marker_specs,
    build_vertical_profiles_figure,
    build_visualization_summary,
)
from hydromodpy.spatial.mesh.gmsh_grid.interactive_3d_viewer import (
    show_interactive_values_3d,
)
from hydromodpy.spatial.mesh.gmsh_grid.plotting_utils import (
    ensure_interactive_backend_for_show,
    show_figures_blocking,
)

plt.switch_backend("Agg")


DEFAULT_CONFIG_FILE = "case_config_3d_fieldparam.toml"
DEFAULT_SECTION = "case"

_POSTPROCESS_DEFAULT_CONFIG_FILE = "case_postprocess_3d.toml"
_VISUALIZATION_DEFAULT_CONFIG_FILE = "case_visualization_3d.toml"
_INTERACTIVE_DEFAULT_CONFIG_FILE = "case_interactive_viewer.toml"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Reference 3D FieldParam discretization case and companion tools."
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run the 3D fieldparam case.")
    run_parser.add_argument("--config-file", default=DEFAULT_CONFIG_FILE)
    run_parser.add_argument("--section", default=DEFAULT_SECTION)
    run_parser.add_argument("--output-summary-json", default=None)
    run_parser.add_argument("--output-values-npy", default=None)
    run_parser.add_argument("--output-overview-png", default=None)
    run_parser.add_argument("--show-plot", action="store_true")

    pp_parser = subparsers.add_parser(
        "postprocess",
        help="Postprocess and export 3D values.",
    )
    pp_parser.add_argument("--config-file", default=_POSTPROCESS_DEFAULT_CONFIG_FILE)
    pp_parser.add_argument("--section", default=DEFAULT_SECTION)
    pp_parser.add_argument("--output-summary-json", default=None)
    pp_parser.add_argument("--output-values-npy", default=None)
    pp_parser.add_argument("--output-vtu", default=None)

    viz_parser = subparsers.add_parser("visualize", help="Build QA figures.")
    viz_parser.add_argument("--config-file", default=_VISUALIZATION_DEFAULT_CONFIG_FILE)
    viz_parser.add_argument("--section", default=DEFAULT_SECTION)
    viz_parser.add_argument("--output-summary-json", default=None)
    viz_parser.add_argument("--output-layers-png", default=None)
    viz_parser.add_argument("--output-profiles-png", default=None)
    viz_parser.add_argument("--show-plot", action="store_true")

    int_parser = subparsers.add_parser(
        "interactive",
        help="Launch PyVista 3D viewer.",
    )
    int_parser.add_argument("--config-file", default=_INTERACTIVE_DEFAULT_CONFIG_FILE)
    int_parser.add_argument("--section", default=DEFAULT_SECTION)
    int_parser.add_argument("--show", dest="show", action="store_true", default=None)
    int_parser.add_argument("--no-show", dest="show", action="store_false")
    int_parser.add_argument("--off-screen", action="store_true")
    int_parser.add_argument("--output-summary-json", default=None)
    int_parser.add_argument("--output-screenshot-png", default=None)
    int_parser.add_argument("--threshold-min", type=float, default=None)
    int_parser.add_argument("--threshold-max", type=float, default=None)
    int_parser.add_argument("--clip-normal", default=None)
    int_parser.add_argument("--highlight-source-cell-index", type=int, default=None)
    int_parser.add_argument("--highlight-prism-index", type=int, default=None)

    args = parser.parse_args(argv)
    if args.command is None:
        args.command = "run"
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


def build_reference_3d_fieldparam_state_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, object]:
    """Build the full state of the main 3D FieldParam discretization case."""

    config_path = resolve_reference_3d_fieldparam_config_path(config_toml)
    cfg = resolve_reference_3d_fieldparam_run_config(config_path, section=section)

    state_2d = build_reference_case_state_from_toml(
        cfg["reference_2d_config"],
        section=str(cfg["reference_2d_section"]),
    )
    state_3d_mesh = build_reference_3d_mesh_state_from_toml(
        cfg["reference_3d_mesh_config"],
        section=str(cfg["reference_3d_mesh_section"]),
    )

    geology_field = state_2d["geology_field"]
    field_param = override_field_param_vertical_profile(
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
    summary = build_reference_3d_fieldparam_summary(
        result=result,
        geology_field=geology_field,
        field_param=field_param,
    )
    return {
        "config_path": config_path,
        "config": cfg,
        "state_2d": state_2d,
        "state_3d_mesh": state_3d_mesh,
        "geology_field": geology_field,
        "field_param": field_param,
        "result": result,
        "mesh_3d": state_3d_mesh["mesh_3d"],
        "mesh_with_values": mesh_with_values,
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
) -> dict[str, object]:
    """Run the main 3D FieldParam discretization case."""

    state = build_reference_3d_fieldparam_state_from_toml(config_toml, section=section)
    config_path = Path(state["config_path"])
    cfg = dict(state["config"])
    result = state["result"]
    mesh_with_values = state["mesh_with_values"]
    summary = dict(state["summary"])

    summary_path = optional_case_output_path(
        config_path,
        config_value=cfg.get("output_summary_json"),
        override_value=output_summary_json,
    )
    values_path = optional_case_output_path(
        config_path,
        config_value=cfg.get("output_values_npy"),
        override_value=output_values_npy,
    )
    overview_path = optional_case_output_path(
        config_path,
        config_value=cfg.get("output_overview_png"),
        override_value=output_overview_png,
    )

    if summary_path is not None:
        write_case_json(summary_path, summary)
        summary["output_summary_json"] = str(summary_path)
    if values_path is not None:
        np.save(values_path, np.asarray(result.values_3d, dtype=float))
        summary["output_values_npy"] = str(values_path)
    if overview_path is not None or show_plot:
        if show_plot:
            ensure_interactive_backend_for_show()
        fig = build_reference_3d_fieldparam_figure(
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


def build_reference_3d_postprocess_state_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, object]:
    """Build the state of the 3D postprocess/export companion step."""

    config_path = resolve_reference_3d_fieldparam_config_path(config_toml)
    cfg = resolve_reference_3d_postprocess_config(config_path, section=section)
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
    summary = build_reference_3d_postprocess_summary(
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
) -> dict[str, object]:
    """Run the postprocess/export companion workflow."""

    state = build_reference_3d_postprocess_state_from_toml(config_toml, section=section)
    config_path = Path(state["config_path"])
    cfg = dict(state["config"])
    mesh_with_values = state["mesh_with_values"]
    summary = dict(state["summary"])

    summary_path = optional_case_output_path(
        config_path,
        config_value=cfg.get("output_summary_json"),
        override_value=output_summary_json,
    )
    values_path = optional_case_output_path(
        config_path,
        config_value=cfg.get("output_values_npy"),
        override_value=output_values_npy,
    )
    vtu_path = optional_case_output_path(
        config_path,
        config_value=cfg.get("output_vtu"),
        override_value=output_vtu,
    )

    if summary_path is not None:
        write_case_json(summary_path, summary)
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


def build_reference_3d_visualization_state_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, object]:
    """Build the state of the lightweight QA-figure companion workflow."""

    config_path = resolve_reference_3d_fieldparam_config_path(config_toml)
    cfg = resolve_reference_3d_visualization_config(config_path, section=section)
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
) -> dict[str, object]:
    """Run the lightweight QA-figure companion workflow."""

    state = build_reference_3d_visualization_state_from_toml(config_toml, section=section)
    config_path = Path(state["config_path"])
    cfg = dict(state["config"])
    mesh_with_values = state["mesh_with_values"]
    marker_specs = list(state["marker_specs"])
    summary = dict(state["summary"])

    summary_path = optional_case_output_path(
        config_path,
        config_value=cfg.get("output_summary_json"),
        override_value=output_summary_json,
    )
    layers_path = optional_case_output_path(
        config_path,
        config_value=cfg.get("output_layers_png"),
        override_value=output_layers_png,
    )
    profiles_path = optional_case_output_path(
        config_path,
        config_value=cfg.get("output_profiles_png"),
        override_value=output_profiles_png,
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
        write_case_json(summary_path, summary)
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
        plt.close(layers_fig)
        plt.close(profiles_fig)
    return summary


def build_reference_interactive_viewer_state_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, object]:
    """Build the state of the interactive PyVista viewer companion workflow."""

    config_path = resolve_reference_3d_fieldparam_config_path(config_toml)
    cfg = resolve_reference_interactive_viewer_config(config_path, section=section)
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
) -> dict[str, object]:
    """Run the interactive PyVista viewer companion workflow."""

    state = build_reference_interactive_viewer_state_from_toml(config_toml, section=section)
    config_path = Path(state["config_path"])
    cfg = dict(state["config"])
    mesh_with_values = state["mesh_with_values"]

    summary_path = optional_case_output_path(
        config_path,
        config_value=cfg.get("output_summary_json"),
        override_value=output_summary_json,
    )
    screenshot_path = optional_case_output_path(
        config_path,
        config_value=cfg.get("output_screenshot_png"),
        override_value=output_screenshot_png,
    )
    do_show = bool(cfg["show"]) if show is None else bool(show)
    effective_off_screen = (
        bool(off_screen) or screenshot_path is not None or not do_show or bool(cfg["off_screen"])
    )
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
        off_screen=effective_off_screen,
        screenshot_path=screenshot_path,
        title="Reference 3D interactive viewer",
    )
    summary = build_reference_interactive_viewer_summary(
        viewer_result=viewer_result,
        cfg=cfg,
        do_show=do_show,
        off_screen=effective_off_screen,
        screenshot_path=screenshot_path,
    )
    if summary_path is not None:
        write_case_json(summary_path, summary)
        summary["output_summary_json"] = str(summary_path)
    return summary


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
    if args.command == "postprocess":
        return _main_postprocess(args)
    if args.command == "visualize":
        return _main_visualize(args)
    if args.command == "interactive":
        return _main_interactive(args)
    return 0


__all__ = [
    "DEFAULT_CONFIG_FILE",
    "DEFAULT_SECTION",
    "build_reference_3d_fieldparam_state_from_toml",
    "build_reference_3d_postprocess_state_from_toml",
    "build_reference_3d_visualization_state_from_toml",
    "build_reference_interactive_viewer_state_from_toml",
    "main",
    "run_reference_3d_fieldparam_case_from_toml",
    "run_reference_3d_postprocess_from_toml",
    "run_reference_3d_visualization_from_toml",
    "run_reference_interactive_viewer_from_toml",
]


if __name__ == "__main__":
    raise SystemExit(main())
