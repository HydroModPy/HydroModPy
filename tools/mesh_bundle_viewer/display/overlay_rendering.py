"""Overlay rendering for the standalone mesh visualization package."""

from __future__ import annotations

from collections.abc import Mapping

from ..bundle_contracts import MeshBundleLike
from .geometry import build_edge_segments
from ..schema import PlotConfig


OVERLAY_STYLES = (
    (
        "show_boundaries",
        lambda edge: str(edge.edge_kind) == "boundary",
        "Limite",
        "black",
        1.0,
    ),
    (
        "show_geology_interfaces",
        lambda edge: str(edge.edge_kind) == "geology_interface",
        "Interface geologique",
        "#c85a00",
        1.2,
    ),
    ("show_river_edges", lambda edge: bool(edge.is_river), "Riviere", "#1f78b4", 1.1),
)


def plot_overlays(
    ax,
    *,
    mesh: MeshBundleLike,
    node_xy_map: Mapping[int, tuple[float, float]],
    plot_config: PlotConfig,
    LineCollection,
) -> None:
    """Draw boundary, geology-interface and river overlays."""

    legend_items: list[tuple[str, str]] = []

    for flag_name, selector, label, color, linewidth in OVERLAY_STYLES:
        if not getattr(plot_config, flag_name):
            continue
        segments = build_edge_segments(
            mesh,
            node_xy_map=node_xy_map,
            selector=selector,
        )
        if not segments:
            continue
        ax.add_collection(LineCollection(segments, colors=color, linewidths=linewidth))
        legend_items.append((label, color))

    if legend_items:
        from matplotlib.lines import Line2D

        ax.add_artist(
            ax.legend(
                handles=[
                    Line2D([0], [0], color=color, lw=1.1, label=label)
                    for label, color in legend_items
                ],
                loc="lower left",
                fontsize=9,
                framealpha=0.95,
                title="Surcouches",
                title_fontsize=10,
            )
        )


__all__ = [
    "OVERLAY_STYLES",
    "plot_overlays",
]
