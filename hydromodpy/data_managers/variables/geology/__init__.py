"""Geology variable — data acquisition, caching, and serving."""

from hydromodpy.data_managers.variables.geology.config import (
    GeologyConfig,
    validate_geology_config_data,
)
from hydromodpy.data_managers.variables.geology.io import (
    infer_source_kind,
    load_geology_encoded_grid,
    load_geology_encoded_grid_on_raster_support,
    load_vector_geology_dataframe,
    resolve_data_path,
)
from hydromodpy.data_managers.variables.geology.manager import GeologyManager
from hydromodpy.data_managers.variables.geology.processing import normalize_zone_key

__all__ = (
    "GeologyConfig",
    "GeologyManager",
    "infer_source_kind",
    "load_geology_encoded_grid",
    "load_geology_encoded_grid_on_raster_support",
    "load_vector_geology_dataframe",
    "normalize_zone_key",
    "resolve_data_path",
    "validate_geology_config_data",
)
