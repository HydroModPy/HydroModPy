"""Geology spatial field — concrete Field implementation for zone-based mapping."""

from hydromodpy.field.geology.geology_field import GeologyField
from hydromodpy.field.geology.geology_mesh import GeologyStructuredMesh

# Re-export for backward-compatible test imports.
from hydromodpy.data_managers.variables.geology.config_cases import (
    validate_geology_config_data,
)

__all__ = ("GeologyField", "GeologyStructuredMesh", "validate_geology_config_data")
