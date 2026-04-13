"""Solver-agnostic flow synthesis figures."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.ticker import ScalarFormatter

from hydromodpy.analysis.display.flow_payloads import (
    FlowCumulativeSeriesPayload,
    FlowSpatialFigurePayload,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.analysis.display.display_config import DisplayOptions


@dataclass(frozen=True)
class _SpatialFieldSpec:
    attr_name: str
    title: str
    colorbar_label: str
    cmap: str
    overlay_topography_contours: bool = False
    robust_quantiles: tuple[float, float] | None = None


FLOW_SPATIAL_FIELD_SPECS: dict[str, _SpatialFieldSpec] = {
    "top_elevation": _SpatialFieldSpec(
        attr_name="top_elevation_m",
        title="Topography",
        colorbar_label="Top elevation [m]",
        cmap="terrain",
    ),
    "watertable_elevation": _SpatialFieldSpec(
        attr_name="watertable_elevation_m",
        title="Hydraulic head",
        colorbar_label="Head [m]",
        cmap="viridis",
        overlay_topography_contours=True,
    ),
    "watertable_depth": _SpatialFieldSpec(
        attr_name="watertable_depth_m",
        title="Water-table depth",
        colorbar_label="Top - h [m]",
        cmap="Blues",
        overlay_topography_contours=True,
    ),
    "seepage_areas": _SpatialFieldSpec(
        attr_name="seepage_areas_m_per_day",
        title="Seepage areas",
        colorbar_label="Seepage [m/day]",
        cmap="Reds",
        robust_quantiles=(0.02, 0.98),
    ),
    "outflow_drain": _SpatialFieldSpec(
        attr_name="outflow_drain_m_per_day",
        title="Drain discharge",
        colorbar_label="Discharge [m/day]",
        cmap="magma",
        robust_quantiles=(0.02, 0.98),
    ),
    "accumulation_flux": _SpatialFieldSpec(
        attr_name="accumulation_flux_m_per_day",
        title="Accumulation flux",
        colorbar_label="Accumulated flow [m/day]",
        cmap="plasma",
        robust_quantiles=(0.02, 0.98),
    ),
}


def _cell_centroids(hydro_mesh) -> np.ndarray:
    """Return one `(n_cells, 2)` centroid array for any HydroMesh."""
    conn = np.asarray(hydro_mesh.flat_connectivity, dtype=int)
    verts = np.asarray(hydro_mesh.vertices, dtype=float)
    centroids = np.zeros((int(conn.shape[0]), 2), dtype=float)
    for idx, node_ids in enumerate(conn):
        polygon = verts[np.asarray(node_ids, dtype=int)]
        centroids[idx, 0] = float(np.mean(polygon[:, 0]))
        centroids[idx, 1] = float(np.mean(polygon[:, 1]))
    return centroids


def _draw_topography_contours(ax: "Axes", hydro_mesh, top_elevation_m: np.ndarray | None) -> None:
    """Overlay light topographic contours from cell-centered elevations."""
    if top_elevation_m is None:
        return
    top = np.asarray(top_elevation_m, dtype=float).reshape(-1)
    finite = np.isfinite(top)
    if int(np.count_nonzero(finite)) < 3:
        return
    finite_top = top[finite]
    if np.isclose(float(np.nanmin(finite_top)), float(np.nanmax(finite_top))):
        return
    centroids = _cell_centroids(hydro_mesh)[finite]
    try:
        levels = np.linspace(
            float(np.nanmin(finite_top)),
            float(np.nanmax(finite_top)),
            7,
        )
        ax.tricontour(
            centroids[:, 0],
            centroids[:, 1],
            finite_top,
            levels=levels,
            colors="k",
            linewidths=0.45,
            alpha=0.35,
        )
    except Exception:
        return


def _resolve_color_limits(
    values: np.ndarray,
    *,
    robust_quantiles: tuple[float, float] | None = None,
) -> tuple[float, float]:
    """Return stable color limits for one finite-valued field."""
    finite = np.asarray(values, dtype=float).reshape(-1)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return 0.0, 1.0

    if robust_quantiles is not None and finite.size >= 8:
        qmin, qmax = robust_quantiles
        vmin = float(np.nanquantile(finite, qmin))
        vmax = float(np.nanquantile(finite, qmax))
    else:
        vmin = float(np.nanmin(finite))
        vmax = float(np.nanmax(finite))

    if np.all(finite >= 0.0) and vmin > 0.0:
        vmin = 0.0
    if np.isclose(vmin, vmax):
        vmax = vmin + 1.0
    return vmin, vmax


def _style_map_axes(
    ax: "Axes",
    *,
    show_xlabel: bool = True,
    show_ylabel: bool = True,
) -> None:
    """Apply one compact, consistent style to map-like axes."""
    ax.set_aspect("equal")
    ax.ticklabel_format(style="plain", axis="both", useOffset=False)
    ax.tick_params(axis="both", labelsize=8, length=3.0, pad=2.0)
    ax.set_xlabel("x (m)" if show_xlabel else "", fontsize=9)
    ax.set_ylabel("y (m)" if show_ylabel else "", fontsize=9)


def _add_compact_colorbar(
    figure,
    ax: "Axes",
    mappable,
    *,
    label: str,
) -> None:
    """Attach one compact colorbar to one axes without overwhelming the panel."""
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="3.8%", pad=0.06)
    colorbar = figure.colorbar(mappable, cax=cax)
    colorbar.set_label(label, fontsize=8.5, labelpad=6.0)
    colorbar.ax.tick_params(labelsize=7.5, length=2.5, pad=1.5)

    formatter = ScalarFormatter(useMathText=True)
    formatter.set_powerlimits((-2, 3))
    colorbar.formatter = formatter
    colorbar.update_ticks()


def _densify_curve(
    x_values: np.ndarray,
    y_values: np.ndarray,
    *,
    points_per_segment: int = 12,
) -> tuple[np.ndarray, np.ndarray]:
    """Linearly densify one monotonic curve for smoother display."""
    x = np.asarray(x_values, dtype=float).reshape(-1)
    y = np.asarray(y_values, dtype=float).reshape(-1)
    if x.size <= 1 or y.size != x.size:
        return x, y

    dense_x: list[float] = []
    for start, end in zip(x[:-1].tolist(), x[1:].tolist(), strict=False):
        if not np.isfinite(start) or not np.isfinite(end) or end <= start:
            continue
        segment = np.linspace(start, end, int(points_per_segment) + 1, dtype=float)[:-1]
        dense_x.extend(segment.tolist())
    dense_x.append(float(x[-1]))
    dense_x_arr = np.asarray(dense_x, dtype=float)
    dense_y_arr = np.interp(dense_x_arr, x, y)
    return dense_x_arr, dense_y_arr


def _annotate_last_value(ax: "Axes", x_values: np.ndarray, y_values: np.ndarray, *, color: str) -> None:
    """Add one compact end-of-curve annotation."""
    x = np.asarray(x_values, dtype=float).reshape(-1)
    y = np.asarray(y_values, dtype=float).reshape(-1)
    finite = np.isfinite(x) & np.isfinite(y)
    if not np.any(finite):
        return
    last_index = int(np.flatnonzero(finite)[-1])
    ax.annotate(
        f"{float(y[last_index]):.1f}",
        xy=(float(x[last_index]), float(y[last_index])),
        xytext=(4.0, 0.0),
        textcoords="offset points",
        fontsize=8,
        color=color,
        ha="left",
        va="center",
    )


def _render_spatial_field(
    ax: "Axes",
    *,
    hydro_mesh,
    values: np.ndarray | None,
    title: str,
    colorbar_label: str,
    cmap: str,
    top_elevation_m: np.ndarray | None = None,
    overlay_topography_contours: bool = False,
    robust_quantiles: tuple[float, float] | None = None,
    show_xlabel: bool = True,
    show_ylabel: bool = True,
):
    """Render one cell-centered field and return the Matplotlib mappable."""
    if values is None:
        ax.text(
            0.5,
            0.5,
            "Unavailable",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
        return None

    from hydromodpy.spatial.mesh.plotting import plot_cell_values

    flat = np.asarray(values, dtype=float).reshape(-1).copy()
    flat[~np.isfinite(flat)] = np.nan
    finite = flat[np.isfinite(flat)]
    if finite.size == 0:
        ax.text(
            0.5,
            0.5,
            "No finite values",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
        return None

    vmin, vmax = _resolve_color_limits(
        finite,
        robust_quantiles=robust_quantiles,
    )

    mappable = plot_cell_values(
        ax,
        hydro_mesh,
        flat,
        cmap=cmap,
        show_mesh=True,
        vmin=vmin,
        vmax=vmax,
    )
    if overlay_topography_contours:
        _draw_topography_contours(ax, hydro_mesh, top_elevation_m)
    _style_map_axes(ax, show_xlabel=show_xlabel, show_ylabel=show_ylabel)
    ax.set_title(title, fontsize=10.5, loc="left", pad=6.0)
    return mappable, colorbar_label


def render_flow_spatial_field(
    ax: "Axes",
    *,
    payload: FlowSpatialFigurePayload,
    field_name: str,
):
    """Render one named flow field from the generic spatial payload."""
    spec = FLOW_SPATIAL_FIELD_SPECS[field_name]
    values = getattr(payload, spec.attr_name)
    return _render_spatial_field(
        ax,
        hydro_mesh=payload.hydro_mesh,
        values=values,
        title=spec.title,
        colorbar_label=spec.colorbar_label,
        cmap=spec.cmap,
        top_elevation_m=payload.top_elevation_m,
        overlay_topography_contours=spec.overlay_topography_contours,
        robust_quantiles=spec.robust_quantiles,
    )


def plot_flow_spatial_field(
    *,
    payload: FlowSpatialFigurePayload,
    field_name: str,
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (7.0, 6.0),
    dpi: int = 300,
):
    """Create one single-panel flow field figure."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure, _single_axes

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    rendered = render_flow_spatial_field(ax, payload=payload, field_name=field_name)
    if rendered is not None:
        mappable, colorbar_label = rendered
        _add_compact_colorbar(fig, ax, mappable, label=colorbar_label)
    fig.suptitle(f"{FLOW_SPATIAL_FIELD_SPECS[field_name].title} | {payload.run_id}", fontsize=11.5, y=0.98)
    fig.subplots_adjust(left=0.08, right=0.94, bottom=0.11, top=0.9)
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax


def render_flow_state_triptych(
    axs,
    *,
    payload: FlowSpatialFigurePayload,
    figure=None,
) -> None:
    """Render the topography/head/depth triptych on three axes."""
    axes = np.asarray(axs, dtype=object).reshape(-1)
    field_names = [
        "top_elevation",
        "watertable_elevation",
        "watertable_depth",
    ]
    for index, (ax, field_name) in enumerate(zip(axes.tolist(), field_names, strict=False)):
        spec = FLOW_SPATIAL_FIELD_SPECS[field_name]
        values = getattr(payload, spec.attr_name)
        rendered = _render_spatial_field(
            ax,
            hydro_mesh=payload.hydro_mesh,
            values=values,
            title=spec.title,
            colorbar_label=spec.colorbar_label,
            cmap=spec.cmap,
            top_elevation_m=payload.top_elevation_m,
            overlay_topography_contours=spec.overlay_topography_contours,
            robust_quantiles=spec.robust_quantiles,
            show_xlabel=True,
            show_ylabel=index == 0,
        )
        if rendered is None or figure is None:
            continue
        mappable, colorbar_label = rendered
        _add_compact_colorbar(figure, ax, mappable, label=colorbar_label)


def plot_flow_state_triptych(
    *,
    payload: FlowSpatialFigurePayload,
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (16.0, 5.4),
    dpi: int = 300,
):
    """Create the solver-agnostic flow synthesis triptych."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure

    fig, axs = make_figure(
        nrows=1,
        ncols=3,
        figsize=figsize,
        dpi=dpi,
        sharex=True,
        sharey=True,
    )
    render_flow_state_triptych(axs, payload=payload, figure=fig)
    fig.suptitle(f"Flow state synthesis | {payload.run_id}", fontsize=11.5, y=0.96)
    fig.subplots_adjust(left=0.05, right=0.985, bottom=0.12, top=0.88, wspace=0.34)
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, axs


def render_flow_recharge_discharge_cumulative(
    axs,
    *,
    payload: FlowCumulativeSeriesPayload,
) -> None:
    """Render cumulative recharge and discharge on stacked axes."""
    axes = np.asarray(axs, dtype=object).reshape(-1)
    if axes.size < 2:
        raise ValueError("Two axes are required for cumulative recharge/discharge")
    top_ax = axes[0]
    bottom_ax = axes[1]

    time_days = np.asarray(payload.time_days, dtype=float).reshape(-1)

    if payload.recharge_cumulative_mm is None:
        top_ax.text(
            0.5,
            0.5,
            "No recharge series",
            ha="center",
            va="center",
            transform=top_ax.transAxes,
        )
        top_ax.set_axis_off()
    else:
        dense_time_days, dense_recharge = _densify_curve(
            time_days,
            np.asarray(payload.recharge_cumulative_mm, dtype=float),
        )
        top_ax.plot(
            dense_time_days,
            dense_recharge,
            color="dodgerblue",
            lw=2.2,
        )
        top_ax.scatter(
            time_days,
            np.asarray(payload.recharge_cumulative_mm, dtype=float),
            color="dodgerblue",
            s=14.0,
            zorder=3,
        )
        _annotate_last_value(
            top_ax,
            time_days,
            np.asarray(payload.recharge_cumulative_mm, dtype=float),
            color="dodgerblue",
        )
        top_ax.set_title("Cumulative recharge", fontsize=10.5, loc="left", pad=5.0)
        top_ax.set_ylabel("Recharge [mm]")
        top_ax.grid(True, alpha=0.25)
        top_ax.tick_params(axis="both", labelsize=8)

    discharge_components = payload.discharge_components_cumulative_mm or {}
    if not discharge_components and payload.discharge_total_cumulative_mm is None:
        bottom_ax.text(
            0.5,
            0.5,
            "No discharge series",
            ha="center",
            va="center",
            transform=bottom_ax.transAxes,
        )
        bottom_ax.set_axis_off()
        return

    palette = ["tab:red", "tab:orange", "tab:brown", "tab:purple"]
    for idx, (label, series) in enumerate(discharge_components.items()):
        dense_time_days, dense_series = _densify_curve(time_days, np.asarray(series, dtype=float))
        color = palette[idx % len(palette)]
        bottom_ax.plot(
            dense_time_days,
            dense_series,
            lw=1.8,
            color=color,
            label=label,
        )
        bottom_ax.scatter(
            time_days,
            np.asarray(series, dtype=float),
            color=color,
            s=10.0,
            zorder=3,
        )
    if payload.discharge_total_cumulative_mm is not None:
        total = np.asarray(payload.discharge_total_cumulative_mm, dtype=float)
        dense_time_days, dense_total = _densify_curve(time_days, total)
        bottom_ax.plot(
            dense_time_days,
            dense_total,
            color="black",
            lw=2.4,
            label="Total discharge",
        )
        bottom_ax.scatter(
            time_days,
            total,
            color="black",
            s=14.0,
            zorder=4,
        )
        _annotate_last_value(bottom_ax, time_days, total, color="black")
    bottom_ax.set_title("Cumulative discharge", fontsize=10.5, loc="left", pad=5.0)
    bottom_ax.set_xlabel("Time [days]")
    bottom_ax.set_ylabel("Discharge [mm]")
    bottom_ax.grid(True, alpha=0.25)
    bottom_ax.tick_params(axis="both", labelsize=8)
    bottom_ax.legend(
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
        fontsize=7.5,
        framealpha=0.9,
        borderaxespad=0.0,
    )


def plot_flow_recharge_discharge_cumulative(
    *,
    payload: FlowCumulativeSeriesPayload,
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (11.0, 6.5),
    dpi: int = 300,
):
    """Create the solver-agnostic cumulative recharge/discharge figure."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure

    fig, axs = make_figure(nrows=2, ncols=1, figsize=figsize, dpi=dpi, sharex=True)
    render_flow_recharge_discharge_cumulative(axs, payload=payload)
    fig.suptitle(f"Recharge and discharge synthesis | {payload.run_id}", fontsize=11.5, y=0.97)
    fig.subplots_adjust(left=0.09, right=0.84, bottom=0.11, top=0.9, hspace=0.22)
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, axs


__all__ = [
    "FLOW_SPATIAL_FIELD_SPECS",
    "plot_flow_recharge_discharge_cumulative",
    "plot_flow_spatial_field",
    "plot_flow_state_triptych",
    "render_flow_recharge_discharge_cumulative",
    "render_flow_spatial_field",
    "render_flow_state_triptych",
]
