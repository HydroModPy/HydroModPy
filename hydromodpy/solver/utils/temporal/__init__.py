"""Temporal discretization utilities for solver workflows."""

from .tmesh_generation import TMeshConfig, TMesh_Generation
from .tmesh_config import TMeshConfigModel, load_tmesh_toml, validate_tmesh_config_data

# Backward-compatible alias.
TGrid_Generation = TMesh_Generation

__all__ = [
    "TMeshConfig",
    "TMeshConfigModel",
    "TMesh_Generation",
    "TGrid_Generation",
    "validate_tmesh_config_data",
    "load_tmesh_toml",
]

