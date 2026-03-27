"""Summary helpers for the reference 3D FieldParam case family."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np


def array_stats(arr) -> dict[str, float]:
    """Return finite-value statistics rounded later by the caller if needed."""

    values = np.asarray(arr, dtype=float)
    finite = values[np.isfinite(values)]
    return {
        "min": round(float(np.min(finite)), 12),
        "max": round(float(np.max(finite)), 12),
        "mean": round(float(np.mean(finite)), 12),
        "sum": round(float(np.sum(finite)), 12),
    }


def build_reference_3d_fieldparam_summary(
    *,
    result,
    geology_field,
    field_param,
) -> dict[str, Any]:
    """Build the stable summary of the main 3D FieldParam discretization run."""

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
        "stats_2d": array_stats(values_2d),
        "stats_3d": array_stats(values_3d),
        "depth_stats": array_stats(depth_3d),
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


def build_reference_3d_postprocess_summary(
    *,
    mesh_with_values,
    state_3d_fieldparam,
    value_name: str,
) -> dict[str, Any]:
    """Build the stable summary of the 3D postprocess/export companion step."""

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


def build_reference_interactive_viewer_summary(
    *,
    viewer_result,
    cfg: Mapping[str, Any],
    do_show: bool,
    off_screen: bool,
    screenshot_path,
) -> dict[str, Any]:
    """Build the stable summary of the interactive viewer companion step."""

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
        "off_screen": bool(off_screen),
    }
    if screenshot_path is not None:
        summary["output_screenshot_png"] = str(screenshot_path)
    return summary


__all__ = [
    "array_stats",
    "build_reference_3d_fieldparam_summary",
    "build_reference_3d_postprocess_summary",
    "build_reference_interactive_viewer_summary",
]
