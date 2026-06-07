"""Cell background rendering for the standalone mesh visualization package."""

from __future__ import annotations

import math


def plot_numeric_cells(
    ax,
    *,
    polygons: list[list[tuple[float, float]]],
    values: list[float],
    color_map: str,
    mesh_edge_color: str,
    mesh_edge_linewidth: float,
    PolyCollection,
    plt,
) -> None:
    """Draw one cell-colored background for a numeric field."""

    finite_values = [value for value in values if math.isfinite(value)]
    if not finite_values:
        collection = PolyCollection(
            polygons,
            facecolors="#d9d9d9",
            edgecolors=mesh_edge_color,
            linewidths=mesh_edge_linewidth,
        )
        ax.add_collection(collection)
        ax.text(
            0.02,
            0.98,
            "Aucune valeur disponible\npour ce champ numerique",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=9,
            bbox={
                "boxstyle": "round",
                "facecolor": "white",
                "alpha": 0.9,
                "edgecolor": "0.7",
            },
        )
        return

    collection = PolyCollection(
        polygons,
        array=values,
        cmap=color_map,
        edgecolors=mesh_edge_color,
        linewidths=mesh_edge_linewidth,
    )
    ax.add_collection(collection)
    plt.colorbar(collection, ax=ax, fraction=0.04, pad=0.02)


def plot_categorical_cells(
    ax,
    *,
    polygons: list[list[tuple[float, float]]],
    values: list[str],
    color_map: str,
    mesh_edge_color: str,
    mesh_edge_linewidth: float,
    matplotlib,
    PolyCollection,
    Patch,
) -> None:
    """Draw one cell-colored background for a categorical field."""

    categories = sorted(set(values))
    resampled_cmap = matplotlib.colormaps.get_cmap(color_map).resampled(max(1, len(categories)))
    facecolors_by_category = {
        category: resampled_cmap(index) for index, category in enumerate(categories)
    }
    collection = PolyCollection(
        polygons,
        facecolors=[facecolors_by_category[value] for value in values],
        edgecolors=mesh_edge_color,
        linewidths=mesh_edge_linewidth,
    )
    ax.add_collection(collection)
    ax.legend(
        handles=[
            Patch(
                facecolor=facecolors_by_category[category],
                edgecolor="0.35",
                label=category,
            )
            for category in categories
        ],
        title="color_field",
        loc="upper left",
        fontsize=9,
        title_fontsize=10,
        framealpha=0.95,
    )


__all__ = [
    "plot_categorical_cells",
    "plot_numeric_cells",
]
