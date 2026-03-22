"""Standalone pedagogical tools for exported mesh bundles.

This package exposes a compact API to:

- load one exported mesh bundle
- render a compact overview figure
- build a stable JSON summary

It is designed for redistribution and review, not for mesh generation.

Recommended public entry points:

- CLI: ``python -m mesh`` via ``mesh.cli.main``
- simple Python usage: ``mesh.run_visualization_from_toml(...)``
- lower-level usage: ``mesh.load_toml_config(...)`` and
  ``mesh.build_visualization_figure(...)``
"""

from mesh.display import (
    build_visualization_figure,
    build_visualization_summary,
    build_visualization_summary_contract,
    has_continuous_node_topography,
)
from mesh.bundle_contracts import (
    CatchmentMeshBundle,
    CatchmentMeshBundleCell,
    CatchmentMeshBundleEdge,
    CatchmentMeshBundleGeologyFraction,
    CatchmentMeshBundleNode,
)
from mesh.loading import (
    MeshVisualizationTomlSchema,
    VisualizationPlotTomlSchema,
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
from mesh.visualization_summary import (
    VISUALIZATION_SUMMARY_SCHEMA_VERSION,
    VisualizationSummary,
)

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
    "MeshVisualizationTomlSchema",
    "MeshBundleLike",
    "MeshCellLike",
    "MeshEdgeLike",
    "MeshNodeLike",
    "MeshVisualizationData",
    "NUMERIC_COLOR_FIELDS",
    "PlotConfig",
    "VisualizationConfig",
    "VisualizationPlotTomlSchema",
    "VisualizationSummary",
    "VISUALIZATION_SUMMARY_SCHEMA_VERSION",
    "build_visualization_figure",
    "build_visualization_summary",
    "build_visualization_summary_contract",
    "has_continuous_node_topography",
    "load_toml_config",
    "load_visualization_data",
    "load_visualization_data_from_toml",
    "run_visualization",
    "run_visualization_from_toml",
]
