"""Affichage et synthese du package `mesh`."""

from mesh.display.figure import (
    build_visualization_figure,
    has_continuous_node_topography,
)
from mesh.display.summary import (
    build_visualization_summary,
)

__all__ = [
    "build_visualization_figure",
    "build_visualization_summary",
    "has_continuous_node_topography",
]
