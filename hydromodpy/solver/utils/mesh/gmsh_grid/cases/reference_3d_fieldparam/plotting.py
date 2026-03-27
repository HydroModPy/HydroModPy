"""Plotting helpers for the reference 3D FieldParam case family."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from hydromodpy.solver.utils.mesh.gmsh_grid.plotting_utils import (
    disable_axis_offset,
    maybe_scientific_colorbar,
)


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


def _draw_summary_boxes(ax, *, summary: Mapping[str, object]) -> None:
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


def build_reference_3d_fieldparam_figure(
    *,
    mesh_with_values,
    summary: Mapping[str, object],
):
    """Build the high-level overview figure of the 3D FieldParam run."""

    from matplotlib import pyplot as plt

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


__all__ = ["build_reference_3d_fieldparam_figure"]
