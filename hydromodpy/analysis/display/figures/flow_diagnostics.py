"""Generic flow diagnostics figures shared by multiple solver backends."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.analysis.display.options import DisplayOptions


def _coerce_time_axis(values) -> np.ndarray:
    """Normalize one time axis payload to a flat array."""
    if values is None:
        return np.asarray([], dtype=float)
    array = np.asarray(values)
    if array.ndim == 0:
        array = array.reshape(1)
    return array.reshape(-1)


def _coerce_component_series(
    components_by_name: dict[str, np.ndarray | list[float] | tuple[float, ...]] | None,
) -> dict[str, np.ndarray]:
    """Normalize a mapping of diagnostic labels to numeric series."""
    if not components_by_name:
        return {}
    normalized: dict[str, np.ndarray] = {}
    for name, values in components_by_name.items():
        series = np.asarray(values, dtype=float).reshape(-1)
        if series.size == 0:
            continue
        normalized[str(name)] = series
    return normalized


def render_flow_mass_balance(
    ax: "Axes",
    *,
    time_values,
    components_by_name: dict[str, np.ndarray | list[float] | tuple[float, ...]] | None,
    net_series: np.ndarray | list[float] | tuple[float, ...] | None = None,
    title: str = "Mass Balance",
    ylabel: str = "Signed flow [m3/s]",
) -> None:
    """Render one signed mass-balance diagnostic plot.

    Positive values represent inflows into the aquifer.
    Negative values represent outflows or storage uptake.
    """
    time_axis = _coerce_time_axis(time_values)
    components = _coerce_component_series(components_by_name)
    if not components:
        ax.text(
            0.5,
            0.5,
            "No mass-balance diagnostics",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
        return

    if time_axis.size == 0:
        first = next(iter(components.values()))
        time_axis = np.arange(1, int(first.size) + 1, dtype=float)

    palette = [
        "tab:blue",
        "tab:orange",
        "tab:green",
        "tab:red",
        "tab:purple",
        "tab:brown",
        "tab:pink",
    ]
    for idx, (name, series) in enumerate(components.items()):
        if series.size != time_axis.size:
            continue
        ax.plot(
            time_axis,
            series,
            marker="o",
            lw=1.8,
            ms=4.0,
            alpha=0.9,
            color=palette[idx % len(palette)],
            label=name,
        )

    if net_series is not None:
        net = np.asarray(net_series, dtype=float).reshape(-1)
        if net.size == time_axis.size:
            ax.plot(
                time_axis,
                net,
                color="black",
                lw=2.4,
                label="Net residual",
            )

    ax.axhline(0.0, color="dimgray", lw=1.0, ls="--", alpha=0.7)
    ax.set_title(title)
    ax.set_xlabel("Stress period")
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=7, framealpha=0.85)


def plot_flow_mass_balance(
    *,
    time_values,
    components_by_name: dict[str, np.ndarray | list[float] | tuple[float, ...]] | None,
    net_series: np.ndarray | list[float] | tuple[float, ...] | None = None,
    title: str = "Mass Balance",
    ylabel: str = "Signed flow [m3/s]",
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (11.0, 4.0),
    dpi: int = 300,
):
    """Create one mass-balance figure, render it, and optionally save it."""
    from hydromodpy.analysis.display.common import (
        _single_axes,
        finalize_figure,
        make_figure,
    )

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_flow_mass_balance(
        ax,
        time_values=time_values,
        components_by_name=components_by_name,
        net_series=net_series,
        title=title,
        ylabel=ylabel,
    )
    fig.tight_layout()
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax


def render_flow_probe_timeseries(
    ax: "Axes",
    *,
    time_values,
    series_by_label: dict[str, np.ndarray | list[float] | tuple[float, ...]] | None,
    title: str = "Probe Time Series",
    ylabel: str = "Value",
) -> None:
    """Render one generic probe-timeseries panel."""
    time_axis = _coerce_time_axis(time_values)
    series_map = _coerce_component_series(series_by_label)
    if not series_map:
        ax.text(
            0.5,
            0.5,
            "No probe time series",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
        return

    if time_axis.size == 0:
        first = next(iter(series_map.values()))
        time_axis = np.arange(0, int(first.size), dtype=float)

    for label, values in series_map.items():
        if values.size != time_axis.size:
            continue
        ax.plot(time_axis, values, marker="o", lw=1.8, ms=3.8, label=label)

    ax.set_title(title)
    ax.set_xlabel("Time")
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=7, framealpha=0.85)


def plot_flow_probe_timeseries(
    *,
    time_values,
    series_by_label: dict[str, np.ndarray | list[float] | tuple[float, ...]] | None,
    title: str = "Probe Time Series",
    ylabel: str = "Value",
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (11.0, 4.5),
    dpi: int = 300,
):
    """Create one probe-timeseries figure, render it, and optionally save it."""
    from hydromodpy.analysis.display.common import (
        _single_axes,
        finalize_figure,
        make_figure,
    )

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_flow_probe_timeseries(
        ax,
        time_values=time_values,
        series_by_label=series_by_label,
        title=title,
        ylabel=ylabel,
    )
    fig.tight_layout()
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax


__all__ = [
    "plot_flow_mass_balance",
    "plot_flow_probe_timeseries",
    "render_flow_mass_balance",
    "render_flow_probe_timeseries",
]
