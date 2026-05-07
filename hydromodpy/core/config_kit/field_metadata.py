"""Typed convention for ``Field(json_schema_extra=...)`` metadata.

The codebase attaches UI hints, calibration bindings, and serialisation flags
through ``json_schema_extra``. This module defines the canonical key set so
typos surface during validation and tooling can rely on a stable contract.

Use :func:`field_metadata` when declaring a new ``Field``::

    from hydromodpy.core.config_kit.field_metadata import field_metadata

    k_aquifer: Annotated[float, Profile.USER] = Field(
        default=1e-5,
        description="Hydraulic conductivity.",
        json_schema_extra=field_metadata(
            widget_type="input",
            unit="m/s",
            display_name_fr="Conductivite hydraulique",
        ),
    )

The helper rejects unknown keys at module import time, catching typos in CI
rather than at first JSON schema export.
"""

from __future__ import annotations

from typing import Any, Final, Literal, TypedDict

WidgetType = Literal["input", "slider", "select"]
"""UI widget hint consumed by the Streamlit/React frontend."""

Stability = Literal["experimental", "stable"]
"""Maturity tag attached to a field."""


class FieldMetadata(TypedDict, total=False):
    """Canonical schema for ``Field.json_schema_extra`` payloads.

    All keys are optional. Frontends may ignore unknown keys, but
    :func:`field_metadata` rejects them so the project keeps a single source
    of truth for metadata conventions.
    """

    widget_type: WidgetType
    unit: str
    display_name_fr: str
    help_text_fr: str
    display_min: float
    display_max: float
    calibrable: Any
    toml_exclude: bool
    group: str
    stability: Stability


_ALLOWED_KEYS: Final[frozenset[str]] = frozenset(FieldMetadata.__annotations__)


def field_metadata(**kwargs: Any) -> dict[str, Any]:
    """Build a validated ``json_schema_extra`` dict.

    Raises
    ------
    ValueError
        If any key is not part of :class:`FieldMetadata`.
    """
    unknown = set(kwargs) - _ALLOWED_KEYS
    if unknown:
        allowed = ", ".join(sorted(_ALLOWED_KEYS))
        offending = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown field_metadata keys: {offending}. Allowed keys: {allowed}")
    return dict(kwargs)


def is_valid_field_metadata(payload: dict[str, Any]) -> bool:
    """Return True when *payload* only contains canonical keys."""
    return set(payload).issubset(_ALLOWED_KEYS)


def unknown_metadata_keys(payload: dict[str, Any]) -> set[str]:
    """Return the set of keys in *payload* that are not canonical."""
    return set(payload) - _ALLOWED_KEYS


__all__ = [
    "FieldMetadata",
    "Stability",
    "WidgetType",
    "field_metadata",
    "is_valid_field_metadata",
    "unknown_metadata_keys",
]
