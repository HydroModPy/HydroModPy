"""Dedicated figures for Boussinesq flow results."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.display.options import DisplayOptions


def _profile_from_cell_columns(
    *,
    cell_centroid_x_m: np.ndarray,
    cell_head_m: np.ndarray,
    cell_z_top_m: np.ndarray,
    cell_z_bottom_m: np.ndarray | None,
    max_columns: int = 64,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
    """Aggregate cell-wise values into an x-oriented profile."""
    x_values = np.asarray(cell_centroid_x_m, dtype=float).reshape(-1)
    head_values = np.asarray(cell_head_m, dtype=float).reshape(-1)
    top_values = np.asarray(cell_z_top_m, dtype=float).reshape(-1)
    bottom_values = (
        None
        if cell_z_bottom_m is None
        else np.asarray(cell_z_bottom_m, dtype=float).reshape(-1)
    )

    valid_mask = (
        np.isfinite(x_values)
        & np.isfinite(head_values)
        & np.isfinite(top_values)
    )
    if bottom_values is not None:
        valid_mask &= np.isfinite(bottom_values)

    if not np.any(valid_mask):
        empty = np.asarray([], dtype=float)
        return empty, empty, empty, None if bottom_values is None else empty

    x_values = x_values[valid_mask]
    head_values = head_values[valid_mask]
    top_values = top_values[valid_mask]
    if bottom_values is not None:
        bottom_values = bottom_values[valid_mask]

    if x_values.size == 1:
        return x_values, head_values, top_values, bottom_values

    rounded_x = np.round(x_values, decimals=9)
    unique_x = np.unique(rounded_x)
    use_exact_columns = unique_x.size <= int(max_columns)

    if use_exact_columns:
        group_keys = unique_x
        indexer = rounded_x
    else:
        n_bins = min(int(max_columns), int(x_values.size))
        edges = np.linspace(float(np.min(x_values)), float(np.max(x_values)), n_bins + 1)
        indexer = np.digitize(x_values, edges[1:-1], right=False).astype(int)
        group_keys = np.arange(n_bins, dtype=int)

    profile_x: list[float] = []
    profile_head: list[float] = []
    profile_top: list[float] = []
    profile_bottom: list[float] = []

    for key in group_keys.tolist():
        if use_exact_columns:
            group_mask = np.isclose(indexer, key, atol=1.0e-9, rtol=0.0)
        else:
            group_mask = indexer == int(key)
        if not np.any(group_mask):
            continue
        profile_x.append(float(np.mean(x_values[group_mask])))
        profile_head.append(float(np.mean(head_values[group_mask])))
        profile_top.append(float(np.mean(top_values[group_mask])))
        if bottom_values is not None:
            profile_bottom.append(float(np.mean(bottom_values[group_mask])))

    x_profile = np.asarray(profile_x, dtype=float)
    order = np.argsort(x_profile)
    bottom_profile = (
        None
        if bottom_values is None
        else np.asarray(profile_bottom, dtype=float)[order]
    )
    return (
        x_profile[order],
        np.asarray(profile_head, dtype=float)[order],
        np.asarray(profile_top, dtype=float)[order],
        bottom_profile,
    )


def render_boussinesq_state(
    ax_map: Axes,
    ax_profile: Axes,
    *,
    node_x_m: np.ndarray,
    node_y_m: np.ndarray,
    triangles: np.ndarray,
    cell_head_m: np.ndarray,
    cell_centroid_x_m: np.ndarray,
    cell_z_top_m: np.ndarray,
    cell_z_bottom_m: np.ndarray | None = None,
) -> None:
    """Render one Boussinesq state as a mesh map and an x-profile."""
    import matplotlib.tri as mtri

    node_x = np.asarray(node_x_m, dtype=float).reshape(-1)
    node_y = np.asarray(node_y_m, dtype=float).reshape(-1)
    triangle_ids = np.asarray(triangles, dtype=int)
    cell_head = np.asarray(cell_head_m, dtype=float).reshape(-1)

    triangulation = mtri.Triangulation(node_x, node_y, triangle_ids)
    map_artist = ax_map.tripcolor(
        triangulation,
        facecolors=cell_head,
        shading="flat",
        cmap="viridis",
    )
    ax_map.triplot(triangulation, color="white", linewidth=0.35, alpha=0.35)
    ax_map.figure.colorbar(map_artist, ax=ax_map, shrink=0.9, label="Head [m]")
    ax_map.set_title("Final Head")
    ax_map.set_xlabel("X [m]")
    ax_map.set_ylabel("Y [m]")
    ax_map.set_aspect("equal")

    x_profile, head_profile, top_profile, bottom_profile = _profile_from_cell_columns(
        cell_centroid_x_m=np.asarray(cell_centroid_x_m, dtype=float),
        cell_head_m=cell_head,
        cell_z_top_m=np.asarray(cell_z_top_m, dtype=float),
        cell_z_bottom_m=(
            None
            if cell_z_bottom_m is None
            else np.asarray(cell_z_bottom_m, dtype=float)
        ),
    )

    if x_profile.size == 0:
        ax_profile.text(
            0.5,
            0.5,
            "No Boussinesq profile data",
            ha="center",
            va="center",
            transform=ax_profile.transAxes,
        )
        ax_profile.set_axis_off()
        return

    if bottom_profile is not None:
        ax_profile.fill_between(
            x_profile,
            bottom_profile,
            head_profile,
            color="dodgerblue",
            alpha=0.25,
            lw=0,
        )
        ax_profile.plot(x_profile, bottom_profile, color="dimgray", lw=1.0, label="Base")
    ax_profile.fill_between(
        x_profile,
        head_profile,
        top_profile,
        color="sandybrown",
        alpha=0.25,
        lw=0,
    )
    ax_profile.scatter(
        np.asarray(cell_centroid_x_m, dtype=float),
        cell_head,
        s=14,
        color="steelblue",
        alpha=0.35,
        edgecolors="none",
        label="Cell heads",
    )
    ax_profile.plot(x_profile, top_profile, color="saddlebrown", lw=1.8, label="Top")
    ax_profile.plot(x_profile, head_profile, color="navy", lw=2.0, label="Water table")
    ax_profile.set_title("X-Aggregated Profile")
    ax_profile.set_xlabel("X [m]")
    ax_profile.set_ylabel("Elevation [m]")
    ax_profile.legend(loc="best")


def plot_boussinesq_state(
    *,
    node_x_m: np.ndarray,
    node_y_m: np.ndarray,
    triangles: np.ndarray,
    cell_head_m: np.ndarray,
    cell_centroid_x_m: np.ndarray,
    cell_z_top_m: np.ndarray,
    cell_z_bottom_m: np.ndarray | None = None,
    options: DisplayOptions | None = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (11.0, 4.5),
    dpi: int = 300,
):
    """Create, render, and optionally save the canonical Boussinesq figure."""
    from hydromodpy.display.common import finalize_figure, make_figure

    fig, axs = make_figure(nrows=1, ncols=2, figsize=figsize, dpi=dpi)
    axes = np.asarray(axs, dtype=object).reshape(-1)
    render_boussinesq_state(
        axes[0],
        axes[1],
        node_x_m=node_x_m,
        node_y_m=node_y_m,
        triangles=triangles,
        cell_head_m=cell_head_m,
        cell_centroid_x_m=cell_centroid_x_m,
        cell_z_top_m=cell_z_top_m,
        cell_z_bottom_m=cell_z_bottom_m,
    )
    fig.tight_layout()
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, tuple(axes.tolist())


__all__ = [
    "plot_boussinesq_state",
    "render_boussinesq_state",
]
