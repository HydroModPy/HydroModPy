"""Field-case geology compatibility layer.

This package keeps the historical `hydromodpy.field.cases.geology` import path
while the implementation lives in `hydromodpy.data_managers.geology`.
"""

from hydromodpy.data_managers.geology import (
    GeologyConfigSchema,
    GeologyField,
    GeologyStructuredMesh,
    load_geology_toml,
    validate_geology_config_data,
)

__all__ = (
    "GeologyField",
    "GeologyStructuredMesh",
    "GeologyConfigSchema",
    "load_geology_toml",
    "validate_geology_config_data",
)

