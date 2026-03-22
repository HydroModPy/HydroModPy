"""Compare the 3D cartesian workflow and the 3D Gmsh extrusion workflow.

This runner is the pedagogical "same geology, two mesh backends" case for 3D.
It aggregates comparable summaries, figures, and vertical profiles so one can
inspect what changes when the same FieldParam pipeline is applied on structured
and extruded prism meshes.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import warnings

from matplotlib import pyplot as plt
import numpy as np

try:
    from pyparsing import PyparsingDeprecationWarning
except Exception:  # pragma: no cover - optional import guard
    PyparsingDeprecationWarning = None

from hydromodpy.field.geology.geology_field import GeologyField
from hydromodpy.field.core.field_param import FieldParam
from hydromodpy.solver.utils.mesh.cartesian_grid.examples.discretization.case_runner import (
    run_discretization_case,
)
from hydromodpy.solver.utils.mesh.cartesian_grid.examples.discretization.run_demo_config import (
    SGridFieldParamDiscretizationConfig,
)
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_config import SGridConfig
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_from_config import (
    build_sgrid_from_config,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases._comparison_utils import (
    array_stats,
    layer_quantiles,
    layer_stats,
    mesh_bounds_xy,
    mesh_footprint_area,
    nearest_cell_index,
    resolve_config_path,
    resolve_output_dir,
    round_float,
    rounded_list,
    shared_bounds,
    show_saved_images_blocking,
    signature_head,
    value_quantiles,
    write_json,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_3d_fieldparam.run_case_3d_fieldparam import (
    build_reference_3d_fieldparam_state_from_toml,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.extruded_mesh_visualization import (
    plot_planar_cell_values,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.plotting_utils import (
    maybe_scientific_colorbar,
)
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_fieldparam_discretization import (
    _compute_layer_center_depths as _compute_cartesian_layer_center_depths,
)

if PyparsingDeprecationWarning is not None:  # pragma: no branch
    warnings.filterwarnings("ignore", category=PyparsingDeprecationWarning)

plt.switch_backend("Agg")


DEFAULT_CARTESIAN_CONFIG = "case_config_cartesian.toml"
DEFAULT_GMSH_CONFIG = "case_config_gmsh.toml"
_PROFILE_TARGETS = (
    ("southwest_quarter", 0.25, 0.25),
    ("center", 0.50, 0.50),
    ("northeast_quarter", 0.75, 0.75),
)
_PROFILE_COLORS = ("#dc2626", "#2563eb", "#16a34a")


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Compare cartesian structured 3D and Gmsh extruded 3D "
            "FieldParam discretizations."
        )
    )
    parser.add_argument("--cartesian-config-file", default=DEFAULT_CARTESIAN_CONFIG)
    parser.add_argument("--gmsh-config-file", default=DEFAULT_GMSH_CONFIG)
    parser.add_argument("--section", default="case")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--no-show-plot", action="store_true")
    return parser.parse_args(argv)


def _extract_cartesian_profile(
    values_3d, depth_3d, *, source_cell_index: int
) -> dict[str, object]:
    arr = np.asarray(values_3d, dtype=float)
    depth = np.asarray(depth_3d, dtype=float)
    _, _, ncol = arr.shape
    source_idx = int(source_cell_index)
    row_idx = int(source_idx // ncol)
    col_idx = int(source_idx % ncol)
    return {
        "source_cell_index": source_idx,
        "row_index": row_idx,
        "col_index": col_idx,
        "layer_indices": [int(v) for v in range(arr.shape[0])],
        "values": rounded_list(arr[:, row_idx, col_idx]),
        "depths": rounded_list(depth[:, row_idx, col_idx]),
    }


def _build_cartesian_summary(
    *,
    geology_field: GeologyField,
    field_param: FieldParam,
    result,
    depth_3d: np.ndarray,
) -> dict[str, object]:
    values_2d = np.asarray(result.values_2d, dtype=float)
    values_3d = np.asarray(result.values_3d, dtype=float)
    return {
        "workflow": "cartesian_structured_3d",
        "mesh_kind": str(result.mesh.kind),
        "cell_type_2d": "quadrilateral",
        "cell_type_3d": "structured_layered",
        "field_id": str(getattr(geology_field, "identifier", "")),
        "field_param_id": str(getattr(field_param, "identifier", "")),
        "field_param_kind": str(getattr(field_param, "kind", "")),
        "shape_2d": [int(v) for v in values_2d.shape],
        "shape_3d": [int(v) for v in values_3d.shape],
        "n_layers": int(values_3d.shape[0]),
        "n_cells_2d": int(values_2d.size),
        "n_cells_3d": int(values_3d.size),
        "bounds_xy": mesh_bounds_xy(result.mesh),
        "footprint_area": mesh_footprint_area(result.mesh),
        "stats_2d": array_stats(values_2d),
        "stats_3d": array_stats(values_3d),
        "depth_stats": array_stats(depth_3d),
        "layer_stats": layer_stats(values_3d),
        "layer_quantiles": layer_quantiles(values_3d),
        "global_value_quantiles": value_quantiles(values_3d),
        "layer_depth_means": [
            round_float(np.mean(np.asarray(depth_3d[layer_idx], dtype=float)))
            for layer_idx in range(values_3d.shape[0])
        ],
        "values_2d_signature_head": signature_head(values_2d),
        "values_3d_signature_head": signature_head(values_3d),
        "depth_signature_head": signature_head(depth_3d),
    }


def _build_gmsh_summary(state_gmsh: Mapping[str, object]) -> dict[str, object]:
    result = state_gmsh["result"]
    mesh_3d = state_gmsh["mesh_3d"]
    mesh_with_values = state_gmsh["mesh_with_values"]
    geology_field = state_gmsh["geology_field"]
    field_param = state_gmsh["field_param"]
    values_2d = np.asarray(result.values_2d, dtype=float)
    values_3d = np.asarray(mesh_with_values.values_3d, dtype=float)
    depth_3d = np.asarray(mesh_with_values.prism_center_depths, dtype=float)
    return {
        "workflow": "gmsh_extruded_3d",
        "mesh_kind": str(mesh_3d.kind),
        "cell_type_2d": str(mesh_3d.cell_type_2d),
        "cell_type_3d": str(mesh_3d.cell_type_3d),
        "field_id": str(getattr(geology_field, "identifier", "")),
        "field_param_id": str(getattr(field_param, "identifier", "")),
        "field_param_kind": str(getattr(field_param, "kind", "")),
        "shape_2d": [int(values_2d.size)],
        "shape_3d": [int(v) for v in values_3d.shape],
        "n_layers": int(values_3d.shape[0]),
        "n_cells_2d": int(values_3d.shape[1]),
        "n_cells_3d": int(values_3d.size),
        "bounds_xy": mesh_bounds_xy(mesh_3d.planar_mesh),
        "bounds_xyz": [round_float(v, ndigits=6) for v in mesh_3d.bounds],
        "footprint_area": mesh_footprint_area(mesh_3d.planar_mesh),
        "stats_2d": array_stats(values_2d),
        "stats_3d": array_stats(values_3d),
        "depth_stats": array_stats(depth_3d),
        "layer_stats": layer_stats(values_3d),
        "layer_quantiles": layer_quantiles(values_3d),
        "global_value_quantiles": value_quantiles(values_3d),
        "layer_depth_means": [
            round_float(np.mean(np.asarray(depth_3d[layer_idx], dtype=float)))
            for layer_idx in range(values_3d.shape[0])
        ],
        "values_2d_signature_head": signature_head(values_2d),
        "values_3d_signature_head": signature_head(values_3d),
        "depth_signature_head": signature_head(depth_3d),
    }


def _build_profile_specs(
    *,
    cartesian_mesh,
    gmsh_mesh,
    shared_bounds_xy: list[float],
) -> list[dict[str, object]]:
    xmin, ymin, xmax, ymax = [float(v) for v in shared_bounds_xy]
    specs: list[dict[str, object]] = []
    for idx, (label, fx, fy) in enumerate(_PROFILE_TARGETS):
        target_x = xmin + float(fx) * (xmax - xmin)
        target_y = ymin + float(fy) * (ymax - ymin)
        cart_index, cart_xy = nearest_cell_index(
            cartesian_mesh, x=target_x, y=target_y
        )
        gmsh_index, gmsh_xy = nearest_cell_index(gmsh_mesh, x=target_x, y=target_y)
        specs.append(
            {
                "label": str(label),
                "marker": str(idx + 1),
                "color": _PROFILE_COLORS[idx % len(_PROFILE_COLORS)],
                "target_xy": [
                    round_float(target_x, ndigits=6),
                    round_float(target_y, ndigits=6),
                ],
                "cartesian_source_cell_index": int(cart_index),
                "cartesian_xy": [
                    round_float(cart_xy[0], ndigits=6),
                    round_float(cart_xy[1], ndigits=6),
                ],
                "gmsh_source_cell_index": int(gmsh_index),
                "gmsh_xy": [
                    round_float(gmsh_xy[0], ndigits=6),
                    round_float(gmsh_xy[1], ndigits=6),
                ],
            }
        )
    return specs


def _build_profile_comparisons(
    *,
    cartesian_state: Mapping[str, object],
    gmsh_state: Mapping[str, object],
    profile_specs: list[dict[str, object]],
) -> list[dict[str, object]]:
    values_3d_cart = np.asarray(cartesian_state["result"].values_3d, dtype=float)
    depth_3d_cart = np.asarray(cartesian_state["depth_3d"], dtype=float)
    gmsh_mesh_with_values = gmsh_state["mesh_with_values"]
    shared_layers = min(
        int(values_3d_cart.shape[0]), int(gmsh_mesh_with_values.n_layers)
    )
    payload: list[dict[str, object]] = []
    for spec in profile_specs:
        cart_profile = _extract_cartesian_profile(
            values_3d_cart,
            depth_3d_cart,
            source_cell_index=int(spec["cartesian_source_cell_index"]),
        )
        gmsh_profile = gmsh_mesh_with_values.extract_vertical_profile(
            int(spec["gmsh_source_cell_index"])
        )
        cart_values = np.asarray(cart_profile["values"], dtype=float)[:shared_layers]
        gmsh_values = np.asarray(gmsh_profile["values"], dtype=float)[:shared_layers]
        cart_depths = np.asarray(cart_profile["depths"], dtype=float)[:shared_layers]
        gmsh_depths = np.asarray(gmsh_profile.get("depths", []), dtype=float)[
            :shared_layers
        ]
        payload.append(
            {
                "label": str(spec["label"]),
                "marker": str(spec["marker"]),
                "color": str(spec["color"]),
                "target_xy": list(spec["target_xy"]),
                "cartesian": {
                    "source_cell_index": int(cart_profile["source_cell_index"]),
                    "row_index": int(cart_profile["row_index"]),
                    "col_index": int(cart_profile["col_index"]),
                    "xy": list(spec["cartesian_xy"]),
                    "values": rounded_list(cart_values),
                    "depths": rounded_list(cart_depths),
                },
                "gmsh": {
                    "source_cell_index": int(gmsh_profile["source_cell_index"]),
                    "xy": list(spec["gmsh_xy"]),
                    "values": rounded_list(gmsh_values),
                    "depths": rounded_list(gmsh_depths),
                },
                "comparison": {
                    "shared_layers": int(shared_layers),
                    "value_mean_abs_delta": round_float(
                        np.mean(np.abs(gmsh_values - cart_values))
                    ),
                    "value_max_abs_delta": round_float(
                        np.max(np.abs(gmsh_values - cart_values))
                    ),
                    "depth_mean_abs_delta": round_float(
                        np.mean(np.abs(gmsh_depths - cart_depths))
                    ),
                },
            }
        )
    return payload


def _build_comparison_summary(
    *,
    cartesian_summary: Mapping[str, object],
    gmsh_summary: Mapping[str, object],
    profile_payload: list[Mapping[str, object]],
) -> dict[str, object]:
    shared_layers = min(
        int(cartesian_summary["n_layers"]), int(gmsh_summary["n_layers"])
    )
    cart_bounds = np.asarray(cartesian_summary["bounds_xy"], dtype=float)
    gmsh_bounds = np.asarray(gmsh_summary["bounds_xy"], dtype=float)
    cart_stats = dict(cartesian_summary["stats_3d"])
    gmsh_stats = dict(gmsh_summary["stats_3d"])
    cart_quantiles = dict(cartesian_summary["global_value_quantiles"])
    gmsh_quantiles = dict(gmsh_summary["global_value_quantiles"])

    layer_mean_delta: list[float] = []
    layer_sum_delta: list[float] = []
    layer_depth_mean_delta: list[float] = []
    layer_quantile_delta: list[dict[str, object]] = []
    for layer_idx in range(shared_layers):
        cart_layer_stats = dict(cartesian_summary["layer_stats"][layer_idx])
        gmsh_layer_stats = dict(gmsh_summary["layer_stats"][layer_idx])
        cart_layer_quantiles = dict(cartesian_summary["layer_quantiles"][layer_idx])
        gmsh_layer_quantiles = dict(gmsh_summary["layer_quantiles"][layer_idx])
        layer_mean_delta.append(
            round_float(
                float(gmsh_layer_stats["mean"]) - float(cart_layer_stats["mean"])
            )
        )
        layer_sum_delta.append(
            round_float(
                float(gmsh_layer_stats["sum"]) - float(cart_layer_stats["sum"])
            )
        )
        layer_depth_mean_delta.append(
            round_float(
                float(gmsh_summary["layer_depth_means"][layer_idx])
                - float(cartesian_summary["layer_depth_means"][layer_idx])
            )
        )
        layer_quantile_delta.append(
            {
                "layer_index": int(layer_idx),
                **{
                    key: round_float(
                        float(gmsh_layer_quantiles[key])
                        - float(cart_layer_quantiles[key])
                    )
                    for key in sorted(cart_layer_quantiles)
                },
            }
        )

    return {
        "comparison_policy": "aggregate_stats_layer_slices_profiles_only",
        "cell_to_cell_equality_attempted": False,
        "shared_layer_count": int(shared_layers),
        "cartesian_shape_3d": list(cartesian_summary["shape_3d"]),
        "gmsh_shape_3d": list(gmsh_summary["shape_3d"]),
        "cartesian_mesh_kind": str(cartesian_summary["mesh_kind"]),
        "gmsh_mesh_kind": str(gmsh_summary["mesh_kind"]),
        "cartesian_cell_type_2d": str(cartesian_summary["cell_type_2d"]),
        "gmsh_cell_type_2d": str(gmsh_summary["cell_type_2d"]),
        "bounds_xy_delta_abs": [
            round_float(v, ndigits=6) for v in np.abs(cart_bounds - gmsh_bounds)
        ],
        "footprint_area_delta": round_float(
            float(gmsh_summary["footprint_area"])
            - float(cartesian_summary["footprint_area"])
        ),
        "footprint_area_relative_delta": round_float(
            (
                float(gmsh_summary["footprint_area"])
                - float(cartesian_summary["footprint_area"])
            )
            / float(cartesian_summary["footprint_area"])
        ),
        "global_stats_delta": {
            key: round_float(float(gmsh_stats[key]) - float(cart_stats[key]))
            for key in ("min", "max", "mean", "sum")
        },
        "global_value_quantile_delta": {
            key: round_float(float(gmsh_quantiles[key]) - float(cart_quantiles[key]))
            for key in sorted(cart_quantiles)
        },
        "layer_mean_delta": layer_mean_delta,
        "layer_sum_delta": layer_sum_delta,
        "layer_depth_mean_delta": layer_depth_mean_delta,
        "layer_quantile_delta": layer_quantile_delta,
        "profile_labels": [str(profile["label"]) for profile in profile_payload],
        "profile_value_mean_abs_delta": [
            round_float(float(profile["comparison"]["value_mean_abs_delta"]))
            for profile in profile_payload
        ],
        "profile_value_max_abs_delta": [
            round_float(float(profile["comparison"]["value_max_abs_delta"]))
            for profile in profile_payload
        ],
        "profile_depth_mean_abs_delta": [
            round_float(float(profile["comparison"]["depth_mean_abs_delta"]))
            for profile in profile_payload
        ],
        "cartesian_values_3d_signature_head": list(
            cartesian_summary["values_3d_signature_head"]
        ),
        "gmsh_values_3d_signature_head": list(gmsh_summary["values_3d_signature_head"]),
    }


def _plot_profile_targets(
    ax, *, specs: list[Mapping[str, object]], system_key: str
) -> None:
    for spec in specs:
        xy = spec[f"{system_key}_xy"]
        ax.scatter(
            [float(xy[0])],
            [float(xy[1])],
            s=68,
            color=str(spec["color"]),
            edgecolors="white",
            linewidths=0.8,
            zorder=8,
        )
        ax.text(
            float(xy[0]),
            float(xy[1]),
            str(spec["marker"]),
            color="white",
            fontsize=9,
            weight="bold",
            ha="center",
            va="center",
            zorder=9,
        )


def _plot_layer_panel(
    ax,
    *,
    mesh,
    values,
    title: str,
    vmin: float,
    vmax: float,
    profile_specs: list[Mapping[str, object]],
    system_key: str,
):
    mappable = plot_planar_cell_values(
        ax,
        mesh=mesh,
        values=values,
        title=title,
        cmap="viridis",
        show_mesh=True,
        vmin=vmin,
        vmax=vmax,
    )
    _plot_profile_targets(ax, specs=profile_specs, system_key=system_key)
    return mappable


def _build_layer_figure(
    *,
    cartesian_state: Mapping[str, object],
    gmsh_state: Mapping[str, object],
    layer_index: int,
    profile_specs: list[Mapping[str, object]],
    output_path: Path,
    vmin: float,
    vmax: float,
) -> None:
    cart_values_3d = np.asarray(cartesian_state["result"].values_3d, dtype=float)
    gmsh_values_3d = np.asarray(gmsh_state["mesh_with_values"].values_3d, dtype=float)
    cart_depth_3d = np.asarray(cartesian_state["depth_3d"], dtype=float)
    gmsh_depth_3d = np.asarray(
        gmsh_state["mesh_with_values"].prism_center_depths, dtype=float
    )

    fig = plt.figure(figsize=(12.5, 5.2), dpi=145)
    axes = fig.subplot_mosaic(
        [["cartesian", "gmsh", "cbar"]],
        width_ratios=[1.0, 1.0, 0.05],
    )

    cart_ax = axes["cartesian"]
    gmsh_ax = axes["gmsh"]
    cbar_ax = axes["cbar"]

    cart_title = (
        f"Cartesian layer {layer_index + 1}\n"
        f"mean depth = {float(np.mean(cart_depth_3d[layer_index])):.1f} m"
    )
    gmsh_title = (
        f"Gmsh layer {layer_index + 1}\n"
        f"mean depth = {float(np.mean(gmsh_depth_3d[layer_index])):.1f} m"
    )
    mappable = _plot_layer_panel(
        cart_ax,
        mesh=cartesian_state["result"].mesh,
        values=cart_values_3d[layer_index],
        title=cart_title,
        vmin=vmin,
        vmax=vmax,
        profile_specs=profile_specs,
        system_key="cartesian",
    )
    _plot_layer_panel(
        gmsh_ax,
        mesh=gmsh_state["mesh_3d"].planar_mesh,
        values=gmsh_values_3d[layer_index],
        title=gmsh_title,
        vmin=vmin,
        vmax=vmax,
        profile_specs=profile_specs,
        system_key="gmsh",
    )

    cbar = fig.colorbar(mappable, cax=cbar_ax, orientation="vertical")
    cbar.set_label("Field parameter value", fontsize=11, rotation=90, labelpad=12)
    cbar.ax.tick_params(labelsize=9)
    maybe_scientific_colorbar(
        cbar, np.concatenate((cart_values_3d.reshape(-1), gmsh_values_3d.reshape(-1)))
    )

    fig.suptitle(
        f"3D comparison by layer {layer_index + 1} (aggregate QA only, no cell-to-cell diff)",
        fontsize=16,
    )
    fig.subplots_adjust(left=0.06, right=0.97, top=0.88, bottom=0.12, wspace=0.18)
    fig.savefig(output_path)
    plt.close(fig)


def _build_vertical_profiles_figure(
    *,
    profile_payload: list[Mapping[str, object]],
    output_path: Path,
) -> None:
    n_profiles = len(profile_payload)
    fig, axes = plt.subplots(
        1, n_profiles, figsize=(4.6 * n_profiles, 4.9), dpi=150, squeeze=False
    )
    axes_flat = list(axes.reshape(-1))
    for ax, profile in zip(axes_flat, profile_payload, strict=True):
        cartesian = dict(profile["cartesian"])
        gmsh = dict(profile["gmsh"])
        ax.plot(
            np.asarray(cartesian["values"], dtype=float),
            np.asarray(cartesian["depths"], dtype=float),
            marker="o",
            ms=5.5,
            lw=2.0,
            color="#d97706",
            label="Cartesian",
        )
        ax.plot(
            np.asarray(gmsh["values"], dtype=float),
            np.asarray(gmsh["depths"], dtype=float),
            marker="s",
            ms=5.0,
            lw=2.0,
            color="#0f766e",
            label="Gmsh",
        )
        ax.set_title(str(profile["label"]).replace("_", " "), fontsize=12)
        ax.set_xlabel("Field parameter value", fontsize=10)
        ax.set_ylabel("Depth [m]", fontsize=10)
        ax.tick_params(labelsize=9)
        ax.grid(True, color="0.90", lw=0.8)
        ax.invert_yaxis()
        ax.text(
            0.02,
            0.02,
            (
                f"C rc=({cartesian['row_index']},{cartesian['col_index']})\n"
                f"G cell={gmsh['source_cell_index']}\n"
                f"target=({float(profile['target_xy'][0]):.0f}, {float(profile['target_xy'][1]):.0f})"
            ),
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=8,
            bbox={
                "boxstyle": "round,pad=0.35",
                "fc": "white",
                "ec": "0.85",
                "alpha": 0.94,
            },
        )
        ax.legend(loc="upper right", fontsize=9, frameon=True)

    fig.suptitle(
        "Vertical profile comparison on shared XY targets",
        fontsize=15,
    )
    fig.subplots_adjust(left=0.06, right=0.985, top=0.87, bottom=0.14, wspace=0.28)
    fig.savefig(output_path)
    plt.close(fig)


def _build_comparison_overview_figure(
    *,
    cartesian_summary: Mapping[str, object],
    gmsh_summary: Mapping[str, object],
    comparison_summary: Mapping[str, object],
    output_path: Path,
) -> None:
    fig = plt.figure(figsize=(13.5, 8.4), dpi=150)
    axes = fig.subplot_mosaic(
        [
            ["summary", "quantiles"],
            ["layers", "profiles"],
        ],
        width_ratios=[0.95, 1.15],
        height_ratios=[0.90, 1.0],
    )

    ax_summary = axes["summary"]
    ax_summary.axis("off")
    summary_lines = [
        ("Shared layers", str(comparison_summary["shared_layer_count"])),
        (
            "3D cells",
            f"C {int(cartesian_summary['n_cells_3d'])} / G {int(gmsh_summary['n_cells_3d'])}",
        ),
        (
            "2D cell types",
            f"C {cartesian_summary['cell_type_2d']} / G {gmsh_summary['cell_type_2d']}",
        ),
        (
            "Footprint delta",
            f"{float(comparison_summary['footprint_area_relative_delta']):+.3%}",
        ),
        (
            "Global mean delta",
            f"{float(comparison_summary['global_stats_delta']['mean']):+.3e}",
        ),
        (
            "Global max delta",
            f"{float(comparison_summary['global_stats_delta']['max']):+.3e}",
        ),
    ]
    for idx, (label, value) in enumerate(summary_lines):
        row = idx // 2
        col = idx % 2
        x = 0.04 + col * 0.48
        y = 0.92 - row * 0.30
        ax_summary.text(
            x,
            y,
            f"{label}\n{value}",
            transform=ax_summary.transAxes,
            ha="left",
            va="top",
            fontsize=13,
            weight="bold",
            color="0.10",
            bbox={
                "boxstyle": "round,pad=0.55",
                "fc": "#f7f7f7",
                "ec": "#c9c9c9",
                "lw": 1.0,
            },
        )

    quantile_labels = ["q05", "q25", "q50", "q75", "q95"]
    x = np.arange(len(quantile_labels), dtype=float)
    cart_quantiles = np.asarray(
        [
            float(cartesian_summary["global_value_quantiles"][key])
            for key in quantile_labels
        ],
        dtype=float,
    )
    gmsh_quantiles = np.asarray(
        [float(gmsh_summary["global_value_quantiles"][key]) for key in quantile_labels],
        dtype=float,
    )
    ax_quantiles = axes["quantiles"]
    ax_quantiles.plot(
        x,
        cart_quantiles,
        marker="o",
        lw=2.1,
        ms=6.5,
        color="#d97706",
        label="Cartesian",
    )
    ax_quantiles.plot(
        x, gmsh_quantiles, marker="s", lw=2.1, ms=6.0, color="#0f766e", label="Gmsh"
    )
    ax_quantiles.set_xticks(x, quantile_labels)
    ax_quantiles.set_title("Global value quantiles", fontsize=14)
    ax_quantiles.set_ylabel("Field parameter value", fontsize=11)
    ax_quantiles.tick_params(labelsize=10)
    ax_quantiles.grid(True, color="0.90", lw=0.8)
    ax_quantiles.legend(loc="best", fontsize=10)

    layer_idx = np.arange(int(comparison_summary["shared_layer_count"]), dtype=float)
    layer_mean_delta = np.asarray(comparison_summary["layer_mean_delta"], dtype=float)
    layer_depth_delta = np.asarray(
        comparison_summary["layer_depth_mean_delta"], dtype=float
    )
    ax_layers = axes["layers"]
    ax_layers.axhline(0.0, color="0.55", lw=0.9)
    ax_layers.plot(
        layer_idx + 1.0,
        layer_mean_delta,
        marker="o",
        lw=2.2,
        color="#2563eb",
        label="Mean value delta",
    )
    ax_layers.set_title("Layer deltas", fontsize=14)
    ax_layers.set_xlabel("Layer index", fontsize=11)
    ax_layers.set_ylabel("Value delta", fontsize=11, color="#2563eb")
    ax_layers.tick_params(axis="x", labelsize=10)
    ax_layers.tick_params(axis="y", labelsize=10, colors="#2563eb")
    ax_layers.grid(True, color="0.92", lw=0.8)
    ax_layers_twin = ax_layers.twinx()
    ax_layers_twin.plot(
        layer_idx + 1.0,
        layer_depth_delta,
        marker="s",
        lw=2.0,
        color="#7c3aed",
        label="Mean depth delta",
    )
    ax_layers_twin.set_ylabel("Depth delta [m]", fontsize=11, color="#7c3aed")
    ax_layers_twin.tick_params(axis="y", labelsize=10, colors="#7c3aed")
    lines = [
        line
        for line in list(ax_layers.get_lines()) + list(ax_layers_twin.get_lines())
        if not str(line.get_label()).startswith("_")
    ]
    ax_layers.legend(
        lines, [line.get_label() for line in lines], loc="best", fontsize=10
    )

    ax_profiles = axes["profiles"]
    labels = list(comparison_summary["profile_labels"])
    x_prof = np.arange(len(labels), dtype=float)
    mean_abs = np.asarray(
        comparison_summary["profile_value_mean_abs_delta"], dtype=float
    )
    max_abs = np.asarray(comparison_summary["profile_value_max_abs_delta"], dtype=float)
    width = 0.36
    ax_profiles.bar(
        x_prof - 0.5 * width,
        mean_abs,
        width=width,
        color="#93c5fd",
        label="Mean |delta|",
    )
    ax_profiles.bar(
        x_prof + 0.5 * width, max_abs, width=width, color="#1d4ed8", label="Max |delta|"
    )
    ax_profiles.set_xticks(
        x_prof, [str(label).replace("_", " ") for label in labels], rotation=10
    )
    ax_profiles.set_title("Profile absolute deltas", fontsize=14)
    ax_profiles.set_ylabel("Field parameter delta", fontsize=11)
    ax_profiles.tick_params(labelsize=10)
    ax_profiles.grid(True, axis="y", color="0.92", lw=0.8)
    ax_profiles.legend(loc="best", fontsize=10)

    fig.suptitle("3D cartesian vs Gmsh aggregate comparison overview", fontsize=16)
    fig.subplots_adjust(
        left=0.055, right=0.98, top=0.91, bottom=0.10, wspace=0.25, hspace=0.25
    )
    fig.savefig(output_path)
    plt.close(fig)


def build_cartesian_3d_state_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, object]:
    config_path = resolve_config_path(config_toml, caller_file=__file__)
    cfg = SGridFieldParamDiscretizationConfig.from_toml(config_path, section=section)
    geology_field = GeologyField.from_dict(cfg.geology)
    field_param = FieldParam.from_dict(cfg.field_param)
    sgrid = build_sgrid_from_config(SGridConfig.from_mapping(cfg.sgrid))
    result = run_discretization_case(cfg)
    depth_3d = _compute_cartesian_layer_center_depths(sgrid) + float(cfg.depth)
    summary = _build_cartesian_summary(
        geology_field=geology_field,
        field_param=field_param,
        result=result,
        depth_3d=depth_3d,
    )
    return {
        "config_path": config_path,
        "config": cfg,
        "geology_field": geology_field,
        "field_param": field_param,
        "sgrid": sgrid,
        "result": result,
        "depth_3d": depth_3d,
        "summary": summary,
    }


def run_comparison_case(
    *,
    cartesian_config_toml: str | Path,
    gmsh_config_toml: str | Path,
    section: str = "case",
    output_dir: str | Path | None = None,
    show_plot: bool = False,
) -> dict[str, object]:
    cartesian_config = resolve_config_path(cartesian_config_toml, caller_file=__file__)
    gmsh_config = resolve_config_path(gmsh_config_toml, caller_file=__file__)
    out_dir = resolve_output_dir(
        "outputs" if output_dir is None else output_dir,
        default_base=Path(__file__).resolve().parent,
    )
    layer_dir = out_dir / "layers"
    layer_dir.mkdir(parents=True, exist_ok=True)

    cartesian_state = build_cartesian_3d_state_from_toml(
        cartesian_config, section=section
    )
    gmsh_state = build_reference_3d_fieldparam_state_from_toml(
        gmsh_config, section=section
    )

    cartesian_summary = dict(cartesian_state["summary"])
    gmsh_summary = _build_gmsh_summary(gmsh_state)
    shared_bounds_xy = shared_bounds(
        list(cartesian_summary["bounds_xy"]),
        list(gmsh_summary["bounds_xy"]),
    )
    profile_specs = _build_profile_specs(
        cartesian_mesh=cartesian_state["result"].mesh,
        gmsh_mesh=gmsh_state["mesh_3d"].planar_mesh,
        shared_bounds_xy=shared_bounds_xy,
    )
    profile_payload = _build_profile_comparisons(
        cartesian_state=cartesian_state,
        gmsh_state=gmsh_state,
        profile_specs=profile_specs,
    )
    comparison_summary = _build_comparison_summary(
        cartesian_summary=cartesian_summary,
        gmsh_summary=gmsh_summary,
        profile_payload=profile_payload,
    )

    cartesian_summary["profile_targets"] = [
        {
            "label": str(spec["label"]),
            "marker": str(spec["marker"]),
            "xy": list(spec["cartesian_xy"]),
            "source_cell_index": int(spec["cartesian_source_cell_index"]),
        }
        for spec in profile_specs
    ]
    gmsh_summary["profile_targets"] = [
        {
            "label": str(spec["label"]),
            "marker": str(spec["marker"]),
            "xy": list(spec["gmsh_xy"]),
            "source_cell_index": int(spec["gmsh_source_cell_index"]),
        }
        for spec in profile_specs
    ]

    combined_values = np.concatenate(
        (
            np.asarray(cartesian_state["result"].values_3d, dtype=float).reshape(-1),
            np.asarray(gmsh_state["mesh_with_values"].values_3d, dtype=float).reshape(
                -1
            ),
        )
    )
    vmin = float(np.nanmin(combined_values))
    vmax = float(np.nanmax(combined_values))

    shared_layers = int(comparison_summary["shared_layer_count"])
    layer_artifacts: list[str] = []
    layer_image_paths: list[Path] = []
    for layer_index in range(shared_layers):
        rel_path = Path("layers") / f"layer_{layer_index + 1:02d}_comparison.png"
        layer_artifacts.append(str(rel_path).replace("\\", "/"))
        layer_image_path = out_dir / rel_path
        layer_image_paths.append(layer_image_path)
        _build_layer_figure(
            cartesian_state=cartesian_state,
            gmsh_state=gmsh_state,
            layer_index=layer_index,
            profile_specs=profile_specs,
            output_path=layer_image_path,
            vmin=vmin,
            vmax=vmax,
        )

    profiles_rel_path = "vertical_profiles_comparison.png"
    profiles_image_path = out_dir / profiles_rel_path
    _build_vertical_profiles_figure(
        profile_payload=profile_payload,
        output_path=profiles_image_path,
    )
    overview_rel_path = "comparison_overview.png"
    overview_image_path = out_dir / overview_rel_path
    _build_comparison_overview_figure(
        cartesian_summary=cartesian_summary,
        gmsh_summary=gmsh_summary,
        comparison_summary=comparison_summary,
        output_path=overview_image_path,
    )

    payload = {
        "cartesian": cartesian_summary,
        "gmsh": gmsh_summary,
        "comparison": comparison_summary,
        "profiles": profile_payload,
        "artifacts": {
            "layer_figures": layer_artifacts,
            "vertical_profiles_figure": profiles_rel_path,
            "comparison_overview_figure": overview_rel_path,
            "shared_bounds_xy": shared_bounds_xy,
        },
    }

    write_json(out_dir / "cartesian_summary.json", cartesian_summary)
    write_json(out_dir / "gmsh_summary.json", gmsh_summary)
    write_json(out_dir / "comparison_summary.json", payload)

    if show_plot:
        show_saved_images_blocking(
            layer_image_paths + [profiles_image_path, overview_image_path]
        )

    return payload


def main(argv=None) -> int:
    args = _parse_args(argv)
    payload = run_comparison_case(
        cartesian_config_toml=args.cartesian_config_file,
        gmsh_config_toml=args.gmsh_config_file,
        section=args.section,
        output_dir=args.output_dir,
        show_plot=(not bool(args.no_show_plot)),
    )
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
