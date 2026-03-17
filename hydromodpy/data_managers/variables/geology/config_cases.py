"""Backward-compatible aliases for standalone geology case config helpers."""

from hydromodpy.data_managers.variables.geology.config import (
    GeologyConfigSchema,
    GeologyLandSeaSchema,
    GeologySourceSchema,
    load_geology_toml,
    validate_geology_config_data,
)

__all__ = [
    "GeologyConfigSchema",
    "GeologyLandSeaSchema",
    "GeologySourceSchema",
    "load_geology_toml",
    "validate_geology_config_data",
]
