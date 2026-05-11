"""Shared field-validator callables for Pydantic configuration models.

These helpers are pure: they depend only on the standard library and accept
a single ``value`` argument like a Pydantic ``@field_validator`` target. They
must stay in ``core`` and may not import any sibling layer.
"""

from __future__ import annotations


def validate_optional_identifier(value: object) -> str | None:
    """Normalize an optional identifier to a stripped string or ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["validate_optional_identifier"]
