"""Dedicated figures for Boussinesq flow results."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.analysis.display.display_config import DisplayOptions


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


def _build_triangulation(
    *,
    node_x_m: np.ndarray,
    node_y_m: np.ndarray,
    triangles: np.ndarray,
):
    """Create the triangulation used by Boussinesq map figures."""
    import matplotlib.tri as mtri

    return mtri.Triangulation(
        np.asarray(node_x_m, dtype=float).reshape(-1),
        np.asarray(node_y_m, dtype=float).reshape(-1),
        np.asarray(triangles, dtype=int),
    )


def _render_cell_scalar_map(
    ax: Axes,
    *,
    triangulation,
    cell_values,
    title: str,
    colorbar_label: str,
    cmap: str = "viridis",
) -> None:
    """Render one scalar field defined per triangular cell."""
    values = np.asarray(cell_values, dtype=float).reshape(-1)
    artist = ax.tripcolor(
        triangulation,
        facecolors=values,
        shading="flat",
        cmap=cmap,
    )
    ax.triplot(triangulation, color="white", linewidth=0.3, alpha=0.25)
    cb = ax.figure.colorbar(artist, ax=ax, shrink=0.75, pad=0.01, label=colorbar_label)
    cb.ax.tick_params(labelsize=7)
    cb.set_label(colorbar_label, fontsize=7)
    ax.set_title(title, fontsize=9)
    ax.set_xlabel("X [m]", fontsize=8)
    ax.set_ylabel("Y [m]", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.set_aspect("equal")


def _saturated_thickness(
    *,
    cell_head_m: np.ndarray,
    cell_z_top_m: np.ndarray,
    cell_z_bottom_m: np.ndarray,
) -> np.ndarray:
    """Return the clipped saturated thickness for the final state."""
    max_thickness = np.maximum(
        np.asarray(cell_z_top_m, dtype=float) - np.asarray(cell_z_bottom_m, dtype=float),
        0.0,
    )
    return np.clip(
        np.asarray(cell_head_m, dtype=float) - np.asarray(cell_z_bottom_m, dtype=float),
        0.0,
        max_thickness,
    )


def _rate_to_mm_per_day(rate_m_s: np.ndarray) -> np.ndarray:
    """Convert one depth rate from m/s to mm/day."""
    return np.asarray(rate_m_s, dtype=float) * 86_400.0 * 1_000.0


def _flux_to_mm_per_day(
    flux_m3_s: np.ndarray | None,
    *,
    cell_area_m2: np.ndarray | None,
) -> np.ndarray | None:
    """Convert one cell-wise volumetric flux to mm/day when areas are known."""
    if flux_m3_s is None or cell_area_m2 is None:
        return None
    flux = np.asarray(flux_m3_s, dtype=float).reshape(-1)
    area = np.asarray(cell_area_m2, dtype=float).reshape(-1)
    return _rate_to_mm_per_day(
        np.divide(flux, area, out=np.zeros_like(flux), where=area > 0.0)
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
    cell_head = np.asarray(cell_head_m, dtype=float).reshape(-1)
    triangulation = _build_triangulation(
        node_x_m=node_x_m,
        node_y_m=node_y_m,
        triangles=triangles,
    )
    _render_cell_scalar_map(
        ax_map,
        triangulation=triangulation,
        cell_values=cell_head,
        title="Final Head",
        colorbar_label="Head [m]",
        cmap="viridis",
    )

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
    ax_profile.set_title("X-Aggregated Profile", fontsize=9)
    ax_profile.set_xlabel("X [m]", fontsize=8)
    ax_profile.set_ylabel("Elevation [m]", fontsize=8)
    ax_profile.tick_params(labelsize=7)
    ax_profile.legend(loc="best", fontsize=7, markerscale=0.7)


def render_boussinesq_diagnostics(
    axs,
    *,
    node_x_m: np.ndarray,
    node_y_m: np.ndarray,
    triangles: np.ndarray,
    cell_head_m: np.ndarray,
    cell_z_top_m: np.ndarray,
    cell_z_bottom_m: np.ndarray,
    cell_area_m2: np.ndarray | None = None,
    cell_saturation_excess_rate_m_s: np.ndarray | None = None,
    cell_drainage_flux_m3_s: np.ndarray | None = None,
) -> None:
    """Render four final-state Boussinesq diagnostics on a 2x2 grid."""
    axes = np.asarray(axs, dtype=object).reshape(-1)
    if axes.size < 4:
        raise ValueError("render_boussinesq_diagnostics requires at least four axes.")

    triangulation = _build_triangulation(
        node_x_m=node_x_m,
        node_y_m=node_y_m,
        triangles=triangles,
    )
    cell_head = np.asarray(cell_head_m, dtype=float).reshape(-1)
    cell_top = np.asarray(cell_z_top_m, dtype=float).reshape(-1)
    cell_bottom = np.asarray(cell_z_bottom_m, dtype=float).reshape(-1)
    thickness = _saturated_thickness(
        cell_head_m=cell_head,
        cell_z_top_m=cell_top,
        cell_z_bottom_m=cell_bottom,
    )
    head_minus_top = cell_head - cell_top
    saturation_excess_mm_day = np.zeros_like(cell_head)
    if cell_saturation_excess_rate_m_s is not None:
        saturation_excess_mm_day = _rate_to_mm_per_day(cell_saturation_excess_rate_m_s)
    drainage_mm_day = np.zeros_like(cell_head)
    drainage_label = "Drainage [m3/s]"
    if cell_drainage_flux_m3_s is not None:
        drainage_rate = _flux_to_mm_per_day(
            cell_drainage_flux_m3_s,
            cell_area_m2=cell_area_m2,
        )
        if drainage_rate is not None:
            drainage_mm_day = drainage_rate
            drainage_label = "Drainage [mm/day]"
        else:
            drainage_mm_day = np.asarray(cell_drainage_flux_m3_s, dtype=float).reshape(-1)

    _render_cell_scalar_map(
        axes[0],
        triangulation=triangulation,
        cell_values=thickness,
        title="Saturated Thickness",
        colorbar_label="Thickness [m]",
        cmap="viridis",
    )
    _render_cell_scalar_map(
        axes[1],
        triangulation=triangulation,
        cell_values=head_minus_top,
        title="Head Minus Top",
        colorbar_label="Head - top [m]",
        cmap="coolwarm",
    )
    _render_cell_scalar_map(
        axes[2],
        triangulation=triangulation,
        cell_values=drainage_mm_day,
        title="Drainage Release",
        colorbar_label=drainage_label,
        cmap="plasma",
    )
    _render_cell_scalar_map(
        axes[3],
        triangulation=triangulation,
        cell_values=saturation_excess_mm_day,
        title="Saturation Excess",
        colorbar_label="Saturation excess [mm/day]",
        cmap="magma",
    )


def render_boussinesq_edge_flux_map(
    ax: Axes,
    *,
    node_x_m: np.ndarray,
    node_y_m: np.ndarray,
    edge_node_a_indices: np.ndarray,
    edge_node_b_indices: np.ndarray,
    boundary_edge_mask: np.ndarray,
    internal_edge_flux_m3_s: np.ndarray,
    imposed_head_edge_flux_m3_s: np.ndarray | None = None,
) -> None:
    """Render internal-edge flux magnitudes and signed boundary exchanges."""
    from matplotlib.collections import LineCollection

    node_x = np.asarray(node_x_m, dtype=float).reshape(-1)
    node_y = np.asarray(node_y_m, dtype=float).reshape(-1)
    node_a = np.asarray(edge_node_a_indices, dtype=int).reshape(-1)
    node_b = np.asarray(edge_node_b_indices, dtype=int).reshape(-1)
    boundary_mask = np.asarray(boundary_edge_mask, dtype=bool).reshape(-1)
    internal_flux = np.asarray(internal_edge_flux_m3_s, dtype=float).reshape(-1)

    segments = np.stack(
        [
            np.column_stack([node_x[node_a], node_y[node_a]]),
            np.column_stack([node_x[node_b], node_y[node_b]]),
        ],
        axis=1,
    )
    interior_mask = ~boundary_mask
    if np.any(interior_mask):
        interior_segments = segments[interior_mask]
        interior_flux = np.abs(internal_flux[interior_mask])
        collection = LineCollection(
            interior_segments,
            cmap="magma",
            linewidths=2.2,
        )
        collection.set_array(interior_flux)
        ax.add_collection(collection)
        cb = ax.figure.colorbar(
            collection,
            ax=ax,
            shrink=0.75,
            pad=0.01,
            label="Internal |Q| [m3/s]",
        )
        cb.ax.tick_params(labelsize=7)
        cb.set_label("Internal |Q| [m3/s]", fontsize=7)

    if imposed_head_edge_flux_m3_s is not None:
        boundary_flux = np.asarray(imposed_head_edge_flux_m3_s, dtype=float).reshape(-1)
        active_boundary = boundary_mask & np.isfinite(boundary_flux) & (boundary_flux != 0.0)
        if np.any(active_boundary):
            boundary_mid_x = 0.5 * (node_x[node_a[active_boundary]] + node_x[node_b[active_boundary]])
            boundary_mid_y = 0.5 * (node_y[node_a[active_boundary]] + node_y[node_b[active_boundary]])
            scatter = ax.scatter(
                boundary_mid_x,
                boundary_mid_y,
                c=boundary_flux[active_boundary],
                cmap="coolwarm",
                s=42,
                edgecolors="black",
                linewidths=0.35,
                zorder=3,
            )
            cb2 = ax.figure.colorbar(
                scatter,
                ax=ax,
                shrink=0.75,
                pad=0.01,
                label="Boundary Q [m3/s]",
            )
            cb2.ax.tick_params(labelsize=7)
            cb2.set_label("Boundary Q [m3/s]", fontsize=7)

    ax.set_title("Final Flux Diagnostics", fontsize=9)
    ax.set_xlabel("X [m]", fontsize=8)
    ax.set_ylabel("Y [m]", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.set_aspect("equal")
    ax.autoscale()
    ax.grid(True, alpha=0.15)


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
    figsize: tuple[float, float] = (16.0, 7.0),
    dpi: int = 100,
):
    """Create, render, and optionally save the canonical Boussinesq figure."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure

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
    fig.tight_layout(pad=0.4)
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, tuple(axes.tolist())


def plot_boussinesq_diagnostics(
    *,
    node_x_m: np.ndarray,
    node_y_m: np.ndarray,
    triangles: np.ndarray,
    cell_head_m: np.ndarray,
    cell_z_top_m: np.ndarray,
    cell_z_bottom_m: np.ndarray,
    cell_area_m2: np.ndarray | None = None,
    cell_saturation_excess_rate_m_s: np.ndarray | None = None,
    cell_drainage_flux_m3_s: np.ndarray | None = None,
    options: DisplayOptions | None = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (16.0, 12.0),
    dpi: int = 100,
):
    """Create and optionally save the Boussinesq diagnostics panel."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure

    fig, axs = make_figure(nrows=2, ncols=2, figsize=figsize, dpi=dpi)
    render_boussinesq_diagnostics(
        axs,
        node_x_m=node_x_m,
        node_y_m=node_y_m,
        triangles=triangles,
        cell_head_m=cell_head_m,
        cell_z_top_m=cell_z_top_m,
        cell_z_bottom_m=cell_z_bottom_m,
        cell_area_m2=cell_area_m2,
        cell_saturation_excess_rate_m_s=cell_saturation_excess_rate_m_s,
        cell_drainage_flux_m3_s=cell_drainage_flux_m3_s,
    )
    fig.tight_layout(pad=0.4)
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, np.asarray(axs, dtype=object)


def plot_boussinesq_edge_flux_map(
    *,
    node_x_m: np.ndarray,
    node_y_m: np.ndarray,
    edge_node_a_indices: np.ndarray,
    edge_node_b_indices: np.ndarray,
    boundary_edge_mask: np.ndarray,
    internal_edge_flux_m3_s: np.ndarray,
    imposed_head_edge_flux_m3_s: np.ndarray | None = None,
    options: DisplayOptions | None = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (14.0, 10.0),
    dpi: int = 100,
):
    """Create and optionally save the final edge-flux map."""
    from hydromodpy.analysis.display.common import (
        _single_axes,
        finalize_figure,
        make_figure,
    )

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_boussinesq_edge_flux_map(
        ax,
        node_x_m=node_x_m,
        node_y_m=node_y_m,
        edge_node_a_indices=edge_node_a_indices,
        edge_node_b_indices=edge_node_b_indices,
        boundary_edge_mask=boundary_edge_mask,
        internal_edge_flux_m3_s=internal_edge_flux_m3_s,
        imposed_head_edge_flux_m3_s=imposed_head_edge_flux_m3_s,
    )
    fig.tight_layout(pad=0.4)
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax


__all__ = [
    "plot_boussinesq_diagnostics",
    "plot_boussinesq_edge_flux_map",
    "plot_boussinesq_state",
    "render_boussinesq_diagnostics",
    "render_boussinesq_edge_flux_map",
    "render_boussinesq_state",
]
