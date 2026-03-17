"""Backward-compatible shim -- all logic now lives in run_case_3d_fieldparam.

This module keeps a thin ``run_reference_3d_visualization_from_toml`` wrapper
so that tests can ``monkeypatch.setattr`` names on *this* module and have the
function pick up the patched versions through its own global scope.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_3d_fieldparam.run_case_3d_fieldparam import (
    _resolve_optional_output_path,
    _write_json,
    build_reference_3d_visualization_state_from_toml,
)

# Re-export names that the monkeypatch-based test patches on this module.
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

__all__ = [
    "build_reference_3d_visualization_state_from_toml",
    "run_reference_3d_visualization_from_toml",
    "build_layer_maps_figure",
    "build_source_cell_marker_specs",
    "build_vertical_profiles_figure",
    "build_visualization_summary",
    "ensure_interactive_backend_for_show",
    "show_figures_blocking",
]


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


if __name__ == "__main__":
    from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_3d_fieldparam.run_case_3d_fieldparam import main

    raise SystemExit(main(["visualize"]))
