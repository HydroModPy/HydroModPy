"""Backward-compatible aliases for standalone geology case config helpers."""

from hydromodpy.data.variables.geology.config import (
    GeologyConfigBlock,
    GeologyLandSea,
    GeologySource,
    load_geology_toml,
    validate_geology_config_data,
)

__all__ = [
    "GeologyConfigBlock",
    "GeologyLandSea",
    "GeologySource",
    "load_geology_toml",
    "validate_geology_config_data",
]
