"""Compare structured-grid and Gmsh discretizations on the same geology input.

This script is a side-by-side benchmark for the 2D workflow. It runs the
existing cartesian example and the Gmsh example from comparable configs, then
collects summaries, plots both meshes, and highlights how the discretized
geology and resulting values differ.

Use it when the question is not "does the Gmsh path run?" but rather "how does
it behave relative to the structured baseline on the same field data?".
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

import numpy as np
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D

from hydromodpy.solver.utils.mesh.cartesian_grid.examples.discretization.case_runner import (
    run_discretization_case,
)
from hydromodpy.solver.utils.mesh.cartesian_grid.examples.discretization.run_demo_2d import (
    _plot_geology_and_result as _plot_cartesian_geology_and_result,
)
from hydromodpy.solver.utils.mesh.cartesian_grid.examples.discretization.run_demo_config import (
    SGridFieldParamDiscretizationConfig,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases._comparison_utils import (
    mesh_bounds_xy,
    resolve_config_path,
    resolve_output_dir,
    show_saved_images_blocking,
    write_json,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_base.plotting import (
    build_reference_case_figure,
    disable_axis_offset,
    maybe_scientific_colorbar,
    plot_left_raw_geology,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_base.run_case_gmsh import (
    build_reference_case_state_from_toml,
)
from hydromodpy.spatial.field.core.field_param import FieldParam
from hydromodpy.spatial.field.geology.geology_field import GeologyField

plt.switch_backend("Agg")


DEFAULT_CARTESIAN_CONFIG = "case_config_cartesian.toml"
DEFAULT_GMSH_CONFIG = "case_config_gmsh.toml"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Compare cartesian and Gmsh 2D discretizations on the same Brittany geology base."
        )
    )
    parser.add_argument("--cartesian-config-file", default=DEFAULT_CARTESIAN_CONFIG)
    parser.add_argument("--gmsh-config-file", default=DEFAULT_GMSH_CONFIG)
    parser.add_argument("--section", default="case")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--no-show-plot", action="store_true")
    return parser.parse_args(argv)


def _plot_cartesian_reference_figure(
    *,
    cfg: SGridFieldParamDiscretizationConfig,
    geology_field: GeologyField,
    mesh,
    mesh_values,
    field_discretization,
    values_2d: np.ndarray,
    output_path: Path,
    show_plot: bool,
) -> None:
    """Render the cartesian reference figure with the current plot contract."""
    _plot_cartesian_geology_and_result(
        cfg=cfg,
        geology_field=geology_field,
        mesh=mesh,
        mesh_values=mesh_values,
        field_discretization=field_discretization,
        values_2d=values_2d,
        output_path=output_path,
        show_plot=show_plot,
    )


def _dominant_zone_summary(
    field_discretization,
) -> tuple[tuple[str, ...], int, int, dict[str, int]]:
    zone_keys, fractions_by_zone = field_discretization.weighted_components()
    mesh = field_discretization.mesh
    stack = np.vstack(
        [
            np.asarray(mesh.to_cell_values(fractions_by_zone[key]), dtype=float).reshape(-1)
            for key in zone_keys
        ]
    )
    max_fraction = np.nanmax(stack, axis=0)
    dominant_idx = np.argmax(stack, axis=0).astype(float)
    valid = np.isfinite(max_fraction) & (max_fraction > 0.0)
    dominant_idx[~valid] = np.nan
    mixed_count = int(np.count_nonzero(valid & (max_fraction < 0.999999)))
    undefined_count = int(np.count_nonzero(~valid))
    dominant_counts: dict[str, int] = {}
    for idx, zone_key in enumerate(zone_keys):
        dominant_counts[str(zone_key)] = int(np.count_nonzero(dominant_idx[valid] == float(idx)))
    return (
        tuple(str(v) for v in zone_keys),
        mixed_count,
        undefined_count,
        dominant_counts,
    )


def _stable_value_summary(values) -> dict[str, object]:
    arr = np.asarray(values, dtype=float).reshape(-1)
    return {
        "value_min": round(float(np.nanmin(arr)), 12),
        "value_max": round(float(np.nanmax(arr)), 12),
        "value_mean": round(float(np.nanmean(arr)), 12),
        "value_sum": round(float(np.nansum(arr)), 12),
        "value_signature_head": [round(float(v), 12) for v in arr[:8]],
    }


def _build_cartesian_summary(
    *,
    cfg: SGridFieldParamDiscretizationConfig,
    geology_field: GeologyField,
    field_param: FieldParam,
    result,
    mesh_values,
) -> dict[str, object]:
    zone_keys, mixed_count, undefined_count, dominant_counts = _dominant_zone_summary(
        result.field_discretization
    )
    payload = {
        "mesh_kind": str(result.mesh.kind),
        "cell_type": "quadrilateral",
        "n_nodes": int(result.mesh.n_nodes),
        "n_cells": int(result.mesh.n_cells),
        "bounds": mesh_bounds_xy(result.mesh),
        "shape": [int(v) for v in np.asarray(result.values_2d).shape],
        "field_id": str(geology_field.identifier),
        "field_param_id": str(field_param.identifier),
        "field_param_kind": str(field_param.kind),
        "n_zone_keys": int(len(zone_keys)),
        "zone_keys": list(zone_keys),
        "mixed_cell_count": int(mixed_count),
        "undefined_cell_count": int(undefined_count),
        "dominant_zone_counts": dominant_counts,
    }
    payload.update(_stable_value_summary(np.asarray(result.values_2d, dtype=float)))
    _ = mesh_values
    _ = cfg
    return payload


def _build_comparison_summary(
    *,
    cartesian: Mapping[str, object],
    gmsh: Mapping[str, object],
) -> dict[str, object]:
    cart_zone_keys = set(str(v) for v in cartesian["zone_keys"])
    gmsh_zone_keys = set(str(v) for v in gmsh["zone_keys"])
    shared_zone_keys = sorted(cart_zone_keys.intersection(gmsh_zone_keys))
    only_cartesian = sorted(cart_zone_keys.difference(gmsh_zone_keys))
    only_gmsh = sorted(gmsh_zone_keys.difference(cart_zone_keys))

    cart_bounds = np.asarray(cartesian["bounds"], dtype=float)
    gmsh_bounds = np.asarray(gmsh["bounds"], dtype=float)
    dominant_zone_count_delta: dict[str, int] = {}
    for zone_key in shared_zone_keys:
        dominant_zone_count_delta[zone_key] = int(
            int(gmsh["dominant_zone_counts"][zone_key])
            - int(cartesian["dominant_zone_counts"][zone_key])
        )

    return {
        "field_id_match": bool(str(cartesian["field_id"]) == str(gmsh["field_id"])),
        "field_param_id_match": bool(
            str(cartesian["field_param_id"]) == str(gmsh["field_param_id"])
        ),
        "shared_zone_key_count": int(len(shared_zone_keys)),
        "shared_zone_keys": shared_zone_keys,
        "zone_keys_only_cartesian": only_cartesian,
        "zone_keys_only_gmsh": only_gmsh,
        "bounds_delta_abs": [round(float(v), 6) for v in np.abs(cart_bounds - gmsh_bounds)],
        "n_cells_cartesian": int(cartesian["n_cells"]),
        "n_cells_gmsh": int(gmsh["n_cells"]),
        "mixed_cell_count_cartesian": int(cartesian["mixed_cell_count"]),
        "mixed_cell_count_gmsh": int(gmsh["mixed_cell_count"]),
        "undefined_cell_count_cartesian": int(cartesian["undefined_cell_count"]),
        "undefined_cell_count_gmsh": int(gmsh["undefined_cell_count"]),
        "value_mean_delta": round(float(gmsh["value_mean"]) - float(cartesian["value_mean"]), 12),
        "value_sum_delta": round(float(gmsh["value_sum"]) - float(cartesian["value_sum"]), 12),
        "value_min_delta": round(float(gmsh["value_min"]) - float(cartesian["value_min"]), 12),
        "value_max_delta": round(float(gmsh["value_max"]) - float(cartesian["value_max"]), 12),
        "dominant_zone_count_delta": dominant_zone_count_delta,
    }


def _draw_structured_mesh_edges(ax, mesh, *, color: str, lw: float, alpha: float) -> None:
    x = np.asarray(mesh.x_plot, dtype=float)
    y = np.asarray(mesh.y_plot, dtype=float)
    for j in range(y.shape[0]):
        ax.plot(x[j, :], y[j, :], color=color, lw=lw, alpha=alpha)
    for i in range(x.shape[1]):
        ax.plot(x[:, i], y[:, i], color=color, lw=lw, alpha=alpha)


def _plot_mesh_value_panel(
    ax,
    *,
    mesh,
    cell_values,
    title: str,
    vmin: float,
    vmax: float,
):
    mappable = mesh.plot_cell_values(
        ax,
        cell_values,
        cmap="viridis",
        show_mesh=True,
        vmin=vmin,
        vmax=vmax,
    )
    ax.set_title(title, fontsize=26)
    ax.set_xlabel("x [m]", fontsize=22)
    ax.set_ylabel("y [m]", fontsize=22)
    ax.tick_params(labelsize=19)
    disable_axis_offset(ax)
    return mappable


def _draw_cartouches_panel(
    ax,
    *,
    cartouches: list[tuple[tuple[float, float, float, float], str]],
    max_entries: int = 12,
    n_cols: int = 1,
    x0: float = 0.02,
    y0: float = 0.88,
    col_width: float = 0.20,
    row_step: float = 0.19,
    label_max_len: int = 28,
    fontsize: float = 7.0,
) -> None:
    shown = cartouches[:max_entries]
    if not shown:
        return

    for i, (rgba, label) in enumerate(shown):
        row = i // n_cols
        col = i % n_cols
        x = x0 + col * col_width
        y = y0 - row * row_step
        short = label if len(label) <= label_max_len else (label[: label_max_len - 3] + "...")
        ax.text(
            x,
            y,
            short,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=fontsize,
            color="0.08",
            bbox={
                "boxstyle": "round,pad=0.36",
                "fc": rgba,
                "ec": "0.30",
                "lw": 0.75,
                "alpha": 0.98,
            },
            clip_on=False,
        )
    if len(cartouches) > len(shown):
        extra_rows = int(np.ceil(len(shown) / float(n_cols)))
        ax.text(
            x0,
            y0 - extra_rows * row_step,
            f"... +{len(cartouches) - len(shown)} more geology entries",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=max(8.0, fontsize * 0.75),
            color="0.25",
        )


def _draw_summary_panel(ax, *, comparison_summary: Mapping[str, object]) -> None:
    metric_blocks = [
        (
            "Cells",
            f"C {comparison_summary['n_cells_cartesian']} | G {comparison_summary['n_cells_gmsh']}",
        ),
        (
            "Mixed",
            (
                f"C {comparison_summary['mixed_cell_count_cartesian']} | "
                f"G {comparison_summary['mixed_cell_count_gmsh']}"
            ),
        ),
        (
            "Undefined",
            (
                f"C {comparison_summary['undefined_cell_count_cartesian']} | "
                f"G {comparison_summary['undefined_cell_count_gmsh']}"
            ),
        ),
        ("Shared Zones", f"{comparison_summary['shared_zone_key_count']}"),
        (
            "Mean / Sum Δ",
            (
                f"{comparison_summary['value_mean_delta']:.3e}\n"
                f"{comparison_summary['value_sum_delta']:.3e}"
            ),
        ),
        (
            "Min / Max Δ",
            (
                f"{comparison_summary['value_min_delta']:.3e}\n"
                f"{comparison_summary['value_max_delta']:.3e}"
            ),
        ),
    ]
    n_blocks = len(metric_blocks)
    for idx, (label, value) in enumerate(metric_blocks):
        x = (idx + 0.5) / float(n_blocks)
        ax.text(
            x,
            0.52,
            f"{label}\n{value}",
            ha="center",
            va="center",
            fontsize=20.0,
            weight="bold",
            transform=ax.transAxes,
            bbox={
                "boxstyle": "round,pad=0.55",
                "fc": "#f7f7f7",
                "ec": "#c9c9c9",
                "lw": 1.15,
                "alpha": 1.0,
            },
        )


def _build_comparison_figure(
    *,
    cartesian_result,
    cartesian_mesh_values,
    gmsh_state: Mapping[str, object],
    output_path: Path,
) -> list[tuple[tuple[float, float, float, float], str]]:
    gmsh_cfg = dict(gmsh_state["config"])
    gmsh_geology = gmsh_state["geology_field"]
    gmsh_mesh = gmsh_state["mesh"]
    gmsh_mesh_values = gmsh_state["mesh_values"]

    cart_values = np.asarray(
        cartesian_result.mesh.to_cell_values(cartesian_mesh_values.cell_values),
        dtype=float,
    )
    gmsh_values = np.asarray(
        gmsh_mesh.to_cell_values(gmsh_mesh_values.cell_values),
        dtype=float,
    )
    combined_values = np.concatenate((cart_values.reshape(-1), gmsh_values.reshape(-1)))
    vmin = float(np.nanmin(combined_values))
    vmax = float(np.nanmax(combined_values))

    fig = plt.figure(figsize=(46.0, 18.5), dpi=165)
    axes = fig.subplot_mosaic(
        [["geology", "cartesian", "gmsh", "cbar"]],
        width_ratios=[1.55, 1.90, 1.90, 0.05],
    )
    ax_geology = axes["geology"]
    ax_cart = axes["cartesian"]
    ax_gmsh = axes["gmsh"]
    ax_cbar = axes["cbar"]

    cartouches = plot_left_raw_geology(
        ax_geology,
        geology_cfg=gmsh_cfg["geology"],
        geology_field=gmsh_geology,
        mesh=gmsh_mesh,
    )
    _draw_structured_mesh_edges(
        ax_geology,
        cartesian_result.mesh,
        color="#d97706",
        lw=0.42,
        alpha=0.72,
    )
    ax_geology.set_title("Shared geology base with both mesh overlays", fontsize=36)
    ax_geology.set_xlabel("x [m]", fontsize=30)
    ax_geology.set_ylabel("y [m]", fontsize=30)
    ax_geology.tick_params(labelsize=25)

    mappable = _plot_mesh_value_panel(
        ax_cart,
        mesh=cartesian_result.mesh,
        cell_values=cartesian_mesh_values.cell_values,
        title="Cartesian final FieldParam values",
        vmin=vmin,
        vmax=vmax,
    )
    ax_cart.set_title("Cartesian final FieldParam values", fontsize=36)
    ax_cart.set_xlabel("x [m]", fontsize=30)
    ax_cart.set_ylabel("y [m]", fontsize=30)
    ax_cart.tick_params(labelsize=25)

    _plot_mesh_value_panel(
        ax_gmsh,
        mesh=gmsh_mesh,
        cell_values=gmsh_mesh_values.cell_values,
        title="Gmsh final FieldParam values",
        vmin=vmin,
        vmax=vmax,
    )
    ax_gmsh.set_title("Gmsh final FieldParam values", fontsize=36)
    ax_gmsh.set_xlabel("x [m]", fontsize=30)
    ax_gmsh.set_ylabel("y [m]", fontsize=30)
    ax_gmsh.tick_params(labelsize=25)

    cbar = fig.colorbar(mappable, cax=ax_cbar, orientation="vertical")
    cbar.set_label("Field parameter value", fontsize=24.0, rotation=90, labelpad=20.0)
    cbar.ax.tick_params(labelsize=20)
    cbar.outline.set_linewidth(0.9)
    maybe_scientific_colorbar(cbar, combined_values)

    fig.suptitle("Comparison QA: shared geology, cartesian mesh vs Gmsh mesh", fontsize=34)
    fig.subplots_adjust(
        left=0.03,
        right=0.988,
        top=0.90,
        bottom=0.08,
        wspace=0.14,
    )
    fig.savefig(output_path)
    plt.close(fig)
    return cartouches


def _build_comparison_legend_metrics_figure(
    *,
    cartouches: list[tuple[tuple[float, float, float, float], str]],
    comparison_summary: Mapping[str, object],
    output_path: Path,
) -> None:
    fig = plt.figure(figsize=(46.0, 16.0), dpi=165)
    axes = fig.subplot_mosaic(
        [["metrics"], ["legend"]],
        height_ratios=[0.42, 0.58],
    )
    ax_metrics = axes["metrics"]
    ax_legend = axes["legend"]

    ax_metrics.axis("off")
    _draw_summary_panel(ax_metrics, comparison_summary=comparison_summary)

    ax_legend.axis("off")
    ax_legend.set_title("Geology legend and mesh overlays", fontsize=32.0, loc="left", pad=12.0)
    ax_legend.legend(
        handles=[
            Line2D([0], [0], color="0.15", lw=5.0, label="Gmsh mesh"),
            Line2D([0], [0], color="#d97706", lw=5.0, label="Cartesian mesh"),
        ],
        loc="upper left",
        fontsize=25.0,
        frameon=True,
        borderaxespad=0.0,
    )
    _draw_cartouches_panel(
        ax_legend,
        cartouches=cartouches,
        max_entries=18,
        n_cols=4,
        x0=0.02,
        y0=0.78,
        col_width=0.245,
        row_step=0.29,
        label_max_len=36,
        fontsize=30.0,
    )

    fig.suptitle("Comparison QA: legend and summary metrics", fontsize=32.0)
    fig.subplots_adjust(
        left=0.03,
        right=0.99,
        top=0.92,
        bottom=0.05,
        hspace=0.18,
    )
    fig.savefig(output_path)
    plt.close(fig)


def run_comparison_case(
    *,
    cartesian_config_toml: str | Path,
    gmsh_config_toml: str | Path,
    section: str = "case",
    output_dir: str | Path | None = None,
    show_plot: bool = False,
) -> dict[str, object]:
    cartesian_config_path = Path(cartesian_config_toml).expanduser().resolve()
    gmsh_config_path = Path(gmsh_config_toml).expanduser().resolve()
    out_dir = resolve_output_dir(
        "outputs" if output_dir is None else output_dir,
        default_base=Path(__file__).resolve().parent,
    )
    cartesian_cfg = SGridFieldParamDiscretizationConfig.from_toml(
        cartesian_config_path,
        section=section,
    )
    cartesian_result = run_discretization_case(cartesian_cfg)
    cartesian_geology = GeologyField.from_dict(cartesian_cfg.geology)
    cartesian_field_param = FieldParam.from_dict(cartesian_cfg.field_param)
    cartesian_mesh_values = cartesian_field_param.to_mesh_field(
        cartesian_result.field_discretization,
        depth=float(cartesian_cfg.depth),
    )
    cartesian_summary = _build_cartesian_summary(
        cfg=cartesian_cfg,
        geology_field=cartesian_geology,
        field_param=cartesian_field_param,
        result=cartesian_result,
        mesh_values=cartesian_mesh_values,
    )

    cartesian_figure = out_dir / "cartesian_reference.png"
    _plot_cartesian_reference_figure(
        cfg=cartesian_cfg,
        geology_field=cartesian_geology,
        mesh=cartesian_result.mesh,
        mesh_values=cartesian_mesh_values,
        field_discretization=cartesian_result.field_discretization,
        values_2d=np.asarray(cartesian_result.values_2d, dtype=float),
        output_path=cartesian_figure,
        show_plot=False,
    )

    gmsh_figure = out_dir / "gmsh_reference.png"
    gmsh_summary_path = out_dir / "gmsh_summary.json"
    gmsh_state = build_reference_case_state_from_toml(gmsh_config_path, section=section)
    gmsh_fig = build_reference_case_figure(
        cfg=gmsh_state["config"],
        geology_field=gmsh_state["geology_field"],
        mesh=gmsh_state["mesh"],
        field_discretization=gmsh_state["field_discretization"],
        mesh_values=gmsh_state["mesh_values"],
    )
    gmsh_fig.savefig(gmsh_figure)
    plt.close(gmsh_fig)
    gmsh_summary = dict(gmsh_state["summary"])
    write_json(gmsh_summary_path, gmsh_summary)

    comparison_summary = _build_comparison_summary(
        cartesian=cartesian_summary,
        gmsh=gmsh_summary,
    )
    payload = {
        "cartesian": cartesian_summary,
        "gmsh": gmsh_summary,
        "comparison": comparison_summary,
    }

    comparison_json = out_dir / "comparison_summary.json"
    write_json(comparison_json, payload)
    write_json(out_dir / "cartesian_summary.json", cartesian_summary)

    comparison_figure = out_dir / "comparison_overview.png"
    cartouches = _build_comparison_figure(
        cartesian_result=cartesian_result,
        cartesian_mesh_values=cartesian_mesh_values,
        gmsh_state=gmsh_state,
        output_path=comparison_figure,
    )
    comparison_legend_metrics_figure = out_dir / "comparison_legend_metrics.png"
    _build_comparison_legend_metrics_figure(
        cartouches=cartouches,
        comparison_summary=comparison_summary,
        output_path=comparison_legend_metrics_figure,
    )

    if show_plot:
        show_saved_images_blocking(
            [
                cartesian_figure,
                gmsh_figure,
                comparison_figure,
                comparison_legend_metrics_figure,
            ],
            figsize_per_image=(7.6, 4.9),
        )

    return payload


def main(argv=None) -> int:
    args = _parse_args(argv)
    cartesian_config = resolve_config_path(args.cartesian_config_file, caller_file=__file__)
    gmsh_config = resolve_config_path(args.gmsh_config_file, caller_file=__file__)
    output_dir = resolve_output_dir(args.output_dir, default_base=cartesian_config.parent)
    payload = run_comparison_case(
        cartesian_config_toml=cartesian_config,
        gmsh_config_toml=gmsh_config,
        section=args.section,
        output_dir=output_dir,
        show_plot=(not bool(args.no_show_plot)),
    )
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
