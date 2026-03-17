"""Outils de distribution pedagogique pour les maillages HydroModPy.

Ce sous-package expose une API compacte pour :

- charger un bundle de maillage exporte ;
- produire une figure de synthese ;
- obtenir un resume JSON avec les informations structurantes.

Il est pense pour un usage de partage et de relecture, pas pour recalculer
les maillages eux-memes.
"""

from hydromodpy_annex.distribution.mesh.bundle_loading import (
    load_visualization_data,
    load_visualization_data_from_toml,
)
from hydromodpy_annex.distribution.mesh.config import (
    load_toml_config,
)
from hydromodpy_annex.distribution.mesh.models import (
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
from hydromodpy_annex.distribution.mesh.summary import (
    build_visualization_summary,
)
from hydromodpy_annex.distribution.mesh.workflow import (
    run_visualization,
    run_visualization_from_toml,
)
from hydromodpy_annex.distribution.mesh.visualization import (
    build_visualization_figure,
    has_continuous_node_topography,
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
