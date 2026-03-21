"""Standalone pedagogical tools for exported mesh bundles.

This package exposes a compact API to:

- load one exported mesh bundle
- render a compact overview figure
- build a stable JSON summary

It is designed for redistribution and review, not for mesh generation.
"""

from mesh.display import (
    build_visualization_figure,
    build_visualization_summary,
    has_continuous_node_topography,
)
from mesh.loading import (
    load_visualization_data,
    load_visualization_data_from_toml,
    load_toml_config,
)
from mesh.schema import (
    ALLOWED_COLOR_FIELDS,
    ALLOWED_TOPOGRAPHY_FIELDS,
    CATEGORICAL_COLOR_FIELDS,
    DEFAULT_CONFIG_FILENAME,
    DEFAULT_TOML_SECTION,
    GeologyFractionLike,
    MeshBundleLike,
    MeshCellLike,
    MeshEdgeLike,
    MeshNodeLike,
    MeshVisualizationData,
    NUMERIC_COLOR_FIELDS,
    PlotConfig,
    VisualizationConfig,
)
from mesh.runner import (
    run_visualization,
    run_visualization_from_toml,
)

__all__ = [
    "ALLOWED_COLOR_FIELDS",
    "ALLOWED_TOPOGRAPHY_FIELDS",
    "CATEGORICAL_COLOR_FIELDS",
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
    "build_visualization_figure",
    "build_visualization_summary",
    "has_continuous_node_topography",
    "load_toml_config",
    "load_visualization_data",
    "load_visualization_data_from_toml",
    "run_visualization",
    "run_visualization_from_toml",
]
