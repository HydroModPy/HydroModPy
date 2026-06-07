"""Public loading helpers for the standalone ``mesh`` package.

Recommended usage:

- ``load_toml_config(...)`` when you only need validated runtime config
- ``load_visualization_data(...)`` when you already have a config object
- ``load_visualization_data_from_toml(...)`` for a simple load-from-file flow
"""

from .bundle_loader import (
    load_visualization_data,
    load_visualization_data_from_toml,
)
from .toml_contracts import (
    MeshVisualizationTomlSchema,
    VisualizationPlotTomlSchema,
)
from .toml_docs import (
    get_toml_parameter_descriptions,
)
from .toml_loader import (
    load_toml_config,
)
from .toml_validation import (
    ValidationError,
)

__all__ = [
    "MeshVisualizationTomlSchema",
    "ValidationError",
    "VisualizationPlotTomlSchema",
    "get_toml_parameter_descriptions",
    "load_toml_config",
    "load_visualization_data",
    "load_visualization_data_from_toml",
]
