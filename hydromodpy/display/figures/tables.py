"""Stats card and station inventory table figures."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.display.options import DisplayOptions


# ------------------------------------------------------------------
# Stats card
# ------------------------------------------------------------------

def render_stats_card(
    ax: Axes,
    *,
    summary: Any,
) -> None:
    """Structured text block with key watershed metrics.

    *summary* must expose the same attributes as
    :class:`~hydromodpy.display.report.summary.OverviewSummary`.
    """
    ax.set_axis_off()

    lines = [
        f"Watershed: {summary.watershed_name}",
        "",
        f"Catchment area: {summary.catchment_area_km2:.1f} km\u00b2",
        f"Elevation: {summary.elevation_min_m:.0f} \u2013 {summary.elevation_max_m:.0f} m "
        f"(mean {summary.elevation_mean_m:.0f} m)",
        "",
        f"Hydrometry stations: {summary.n_hydrometry_stations}",
        f"Piezometry stations: {summary.n_piezometry_stations}",
        f"Intermittency stations: {summary.n_intermittency_stations}",
    ]
    if summary.geology_types:
        lines.append(f"Geology types: {len(summary.geology_types)}")
    if summary.mean_annual_precipitation_mm is not None:
        lines.append(f"Mean annual precipitation: {summary.mean_annual_precipitation_mm:.0f} mm")
    if summary.mean_annual_etp_mm is not None:
        lines.append(f"Mean annual ETP: {summary.mean_annual_etp_mm:.0f} mm")

    text = "\n".join(lines)
    ax.text(
        0.05, 0.95, text,
        transform=ax.transAxes,
        verticalalignment="top",
        fontsize=9,
        family="monospace",
        linespacing=1.6,
    )
    ax.set_title("Watershed overview", fontsize=10, fontweight="bold")


def plot_stats_card(
    *,
    summary: Any,
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (6, 5),
    dpi: int = 300,
):
    """Create a stats-card figure, render, and optionally save."""
    from hydromodpy.display.common import finalize_figure, make_figure, _single_axes

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_stats_card(ax, summary=summary)
    fig.tight_layout()
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax


# ------------------------------------------------------------------
# Station inventory
# ------------------------------------------------------------------

def render_station_inventory(
    ax: Axes,
    *,
    inventory: list[dict[str, Any]],
) -> None:
    """Matplotlib table listing stations.

    *inventory* is a flat ``list[dict]`` with keys
    ``type``, ``id``, ``x``, ``y``, ``start``, ``end``.
    """
    ax.set_axis_off()

    if not inventory:
        ax.text(0.5, 0.5, "No stations found", ha="center", va="center",
                transform=ax.transAxes, fontsize=10)
        return

    columns = ["Type", "ID", "X", "Y", "Start", "End"]
    cell_text = []
    for row in inventory:
        cell_text.append([
            str(row.get("type", "")),
            str(row.get("id", "")),
            f"{row.get('x', 0):.0f}",
            f"{row.get('y', 0):.0f}",
            str(row.get("start", "")),
            str(row.get("end", "")),
        ])

    table = ax.table(
        cellText=cell_text,
        colLabels=columns,
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(6)
    table.scale(1.0, 1.2)
    ax.set_title("Station inventory", fontsize=10, fontweight="bold")


def plot_station_inventory(
    *,
    inventory: list[dict[str, Any]],
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] | None = None,
    dpi: int = 300,
):
    """Create a station-inventory figure, render, and optionally save."""
    from hydromodpy.display.common import finalize_figure, make_figure, _single_axes

    if figsize is None:
        figsize = (10, max(3, 0.4 * len(inventory) + 1))
    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_station_inventory(ax, inventory=inventory)
    fig.tight_layout()
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax
