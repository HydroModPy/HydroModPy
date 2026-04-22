"""Core runtime contracts for the standalone ``mesh`` package.

This module intentionally describes runtime configuration and shared execution
state only:

- public constants such as the default TOML section
- dataclasses used once TOML content has been validated and paths resolved

The bundle data model itself lives in ``mesh.bundle_contracts`` so that bundle
records and visualization configuration remain easy to distinguish.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .bundle_contracts import (
    CatchmentMeshBundle,
    CatchmentMeshBundleCell,
    CatchmentMeshBundleEdge,
    CatchmentMeshBundleGeologyFraction,
    CatchmentMeshBundleNode,
    GeologyFractionLike,
    MeshBundleLike,
    MeshCellLike,
    MeshEdgeLike,
    MeshNodeLike,
)

DEFAULT_CONFIG_FILENAME = "config_example.toml"
DEFAULT_TOML_SECTION = "mesh_distribution"

NUMERIC_COLOR_FIELDS = {
    "area_m2",
    "z_top_centroid",
    "z_top_mean",
    "z_bottom_centroid",
    "z_bottom_mean",
    "hydraulic_conductivity_m_s",
    "storage_coefficient",
}
CATEGORICAL_COLOR_FIELDS = {
    "geology_code",
    "geology_key",
}
ALLOWED_COLOR_FIELDS = NUMERIC_COLOR_FIELDS | CATEGORICAL_COLOR_FIELDS
ALLOWED_TOPOGRAPHY_FIELDS = {
    "z_top_centroid",
    "z_top_mean",
}


@dataclass(frozen=True)
class PlotConfig:
    """Figure-specific rendering options.

    This is the nested plotting block inside :class:`VisualizationConfig`.
    """

    color_field: str = "geology_key"
    color_map: str = "viridis"
    figure_size: tuple[float, float] = (11.0, 9.0)
    dpi: int = 160
    title: str | None = None
    show_topography_panel: bool = True
    topography_field: str = "z_top_mean"
    topography_cmap: str = "terrain"
    topography_title: str | None = None
    show_mesh_edges: bool = True
    mesh_edge_color: str = "0.35"
    mesh_edge_linewidth: float = 0.55
    show_boundaries: bool = True
    show_geology_interfaces: bool = True
    show_river_edges: bool = True
    annotate_cell_ids: bool = False


@dataclass(frozen=True)
class VisualizationConfig:
    """Fully resolved runtime configuration for one visualization run.

    Paths are already resolved against the TOML file location by the time this
    object is created.
    """

    bundle_dir: Path
    figure_output_path: Path | None = None
    summary_output_path: Path | None = None
    show_window: bool = False
    plot: PlotConfig = PlotConfig()


@dataclass(frozen=True)
class MeshVisualizationData:
    """Central in-memory payload passed through the runner.

    This object pairs one loaded mesh bundle with one resolved runtime config.
    """

    mesh: MeshBundleLike
    config: VisualizationConfig


__all__ = [
    "ALLOWED_COLOR_FIELDS",
    "ALLOWED_TOPOGRAPHY_FIELDS",
    "CATEGORICAL_COLOR_FIELDS",
    "CatchmentMeshBundle",
    "CatchmentMeshBundleCell",
    "CatchmentMeshBundleEdge",
    "CatchmentMeshBundleGeologyFraction",
    "CatchmentMeshBundleNode",
    "DEFAULT_CONFIG_FILENAME",
    "DEFAULT_TOML_SECTION",
    "GeologyFractionLike",
    "MeshBundleLike",
    "MeshCellLike",
    "MeshEdgeLike",
    "MeshNodeLike",
    "MeshVisualizationData",
    "NUMERIC_COLOR_FIELDS",
    "PlotConfig",
    "VisualizationConfig",
]
