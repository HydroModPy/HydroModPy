"""Frontend hooks: JSON Schema export + partial field validator.

This sub-package exposes two stable integration points for external user
interfaces (Angular, React, ...). There is **no HTTP server**:
the core stays pure Python. Consumers hit these helpers via the Python
API or the ``hmp config schema --bundle`` CLI and ship the resulting JSON over whatever
transport they prefer. Every function takes the root configuration model as
its first argument, so this package never imports ``hydromodpy.config``.

Public API::

    from hydromodpy.schema import export_full_schema, validate_field

    export_full_schema("./schema/", root=HydroModPyConfig)
    result = validate_field("flow.param_payload.Sy", 1.5, root=HydroModPyConfig)
"""

from __future__ import annotations

from hydromodpy.schema.config_schema import (
    build_config_meta,
    build_field_validators,
    export_full_schema,
)
from hydromodpy.schema.partial_validator import (
    ValidationResult,
    validate_field,
)

__all__ = [
    "build_config_meta",
    "build_field_validators",
    "export_full_schema",
    "validate_field",
    "ValidationResult",
]
