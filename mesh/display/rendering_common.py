"""Shared rendering helpers for the standalone mesh visualization package."""

from __future__ import annotations

from mesh.bundle_contracts import MeshBundleLike
from mesh.schema import PlotConfig


def load_matplotlib(*, show_window: bool):
    """Load matplotlib and force a non-interactive backend when needed."""

    import matplotlib

    if not show_window:
        try:
            matplotlib.use("Agg", force=True)
        except Exception:
            pass

    from matplotlib import pyplot as plt
    from matplotlib.collections import LineCollection, PolyCollection
    from matplotlib.patches import Patch

    return matplotlib, plt, LineCollection, PolyCollection, Patch


def get_mesh_edge_style(plot_config: PlotConfig) -> tuple[str, float]:
    """Return the mesh-edge style applied to cell collections."""

    if not plot_config.show_mesh_edges:
        return ("none", 0.0)
    return (str(plot_config.mesh_edge_color), float(plot_config.mesh_edge_linewidth))


def build_default_panel_title(*, heading: str, field_name: str) -> str:
    """Build a coherent default title for one panel."""

    return f"{heading}\n{field_name}"


def plot_cell_annotations(ax, *, mesh: MeshBundleLike, plot_config: PlotConfig) -> None:
    """Add cell ids when the option is enabled."""

    if not plot_config.annotate_cell_ids:
        return

    for cell in mesh.cells:
        ax.text(
            float(cell.centroid_x),
            float(cell.centroid_y),
            str(cell.cell_id),
            ha="center",
            va="center",
            fontsize=7,
            color="0.15",
        )


__all__ = [
    "build_default_panel_title",
    "get_mesh_edge_style",
    "load_matplotlib",
    "plot_cell_annotations",
]
