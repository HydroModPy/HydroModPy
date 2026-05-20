"""Pre-validators for the Boussinesq runtime knobs on FlowConfig.

These free functions implement the normalization logic for the 13 flat
``runtime_*`` / ``vi_*`` / ``ts_vi_*`` fields kept on :class:`FlowConfig`
for backward-compatible TOML payloads. Extracting them keeps
``flow_config.py`` focused on the field declarations.
"""

from __future__ import annotations

_RUNTIME_BACKENDS = ("local", "scipy", "scipy_sparse", "petsc")
_SURFACE_MODELS = (
    "auto",
    "regularized_partition",
    "complementarity",
    "vi_obstacle",
    "ts_vi_obstacle",
)
_BOOL_TRUE = {"true", "1", "yes", "on"}
_BOOL_FALSE = {"false", "0", "no", "off"}


def normalize_runtime_backend(value: object) -> str:
    """Normalize the optional Boussinesq runtime backend selector."""
    text = str(value or "local").strip().lower()
    if text not in _RUNTIME_BACKENDS:
        raise ValueError(
            "flow.runtime_backend must be 'local', 'scipy', 'scipy_sparse', or 'petsc'"
        )
    return text


def normalize_surface_interaction_model(value: object) -> str:
    """Normalize the optional Boussinesq surface-interaction selector."""
    text = str(value or "auto").strip().lower() or "auto"
    if text not in _SURFACE_MODELS:
        raise ValueError(
            "flow.surface_interaction_model must be 'auto', "
            "'regularized_partition', 'complementarity', 'vi_obstacle', "
            "or 'ts_vi_obstacle'"
        )
    return text


def normalize_positive_int_or_none(value: object, *, field: str) -> int | None:
    """Validate an optional strictly-positive integer override."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"flow.{field} must be a positive integer")
    numeric = float(value)
    if not numeric.is_integer() or numeric <= 0:
        raise ValueError(f"flow.{field} must be a positive integer")
    return int(numeric)


def normalize_positive_int(value: object, *, field: str, default: int) -> int:
    """Validate a required strictly-positive integer with a default."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ValueError(f"flow.{field} must be a positive integer")
    numeric = float(value)
    if not numeric.is_integer() or numeric <= 0:
        raise ValueError(f"flow.{field} must be a positive integer")
    return int(numeric)


def normalize_bool(value: object, *, field: str) -> bool:
    """Validate a boolean flag accepting common string forms."""
    if value is None or value == "":
        return False
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _BOOL_TRUE:
        return True
    if text in _BOOL_FALSE:
        return False
    raise ValueError(f"flow.{field} must be a boolean")


def normalize_positive_float(value: object, *, field: str, default: float) -> float:
    """Validate a strictly-positive float with a default."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ValueError(f"flow.{field} must be a positive number")
    numeric = float(value)
    if numeric <= 0.0:
        raise ValueError(f"flow.{field} must be a positive number")
    return numeric


def normalize_positive_float_or_none(value: object, *, field: str) -> float | None:
    """Validate an optional strictly-positive float override."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"flow.{field} must be a positive number")
    numeric = float(value)
    if numeric <= 0.0:
        raise ValueError(f"flow.{field} must be a positive number")
    return numeric


__all__ = [
    "normalize_bool",
    "normalize_positive_float",
    "normalize_positive_float_or_none",
    "normalize_positive_int",
    "normalize_positive_int_or_none",
    "normalize_runtime_backend",
    "normalize_surface_interaction_model",
]
