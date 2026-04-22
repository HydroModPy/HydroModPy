"""Frontend hooks: JSON Schema export + partial field validator.

This sub-package exposes two stable integration points for external user
interfaces (Streamlit, Angular, React, ...). There is **no HTTP server**:
the core stays pure Python. Consumers hit these helpers via the Python
API or the ``hmp schema`` CLI and ship the resulting JSON over whatever
transport they prefer.

Public API::

    from hydromodpy.schema import export_full_schema, validate_field

    export_full_schema("./schema/")
    result = validate_field("flow.param_payload.Sy", 1.5)
"""

from __future__ import annotations

from hydromodpy.schema.export import (
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
