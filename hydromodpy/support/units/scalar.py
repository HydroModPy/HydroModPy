"""Helpers to parse scalar values with optional inline units."""

from __future__ import annotations

import re
from numbers import Real


_SCALAR_WITH_OPTIONAL_UNIT_PATTERN = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(.*?)\s*$"
)


def canonical_unit_token(unit: str) -> str:
    """Lowercase, strip, and remove spaces from a unit string."""
    return "".join(str(unit).strip().lower().split())


# Keep underscore alias for internal callers.
_canonical_unit_token = canonical_unit_token


def parse_scalar_and_unit(
    value: object,
    *,
    location: str,
    default_unit: str,
    explicit_unit: str | None = None,
) -> tuple[float, str]:
    """Parse one scalar payload and resolve its unit token.

    Accepted ``value`` forms:
    - numeric (``int``/``float``): unit comes from ``explicit_unit`` or ``default_unit``.
    - string: either ``"<number>"`` or ``"<number> <unit>"``.

    If both an inline unit (inside ``value``) and ``explicit_unit`` are provided,
    they must match (case/spacing-insensitive).
    """
    unit_from_field: str | None = None
    if explicit_unit is not None:
        unit_from_field = str(explicit_unit).strip()
        if unit_from_field == "":
            raise ValueError(f"{location} has an empty explicit unit.")

    default_unit_token = str(default_unit).strip()
    if default_unit_token == "":
        raise ValueError(f"{location} requires a non-empty default_unit.")

    inline_unit: str | None = None
    if isinstance(value, bool):
        raise TypeError(f"{location} must be numeric or a string like '12.3 m'.")
    if isinstance(value, Real):
        scalar = float(value)
    elif isinstance(value, str):
        token = value.strip()
        if token == "":
            raise ValueError(f"{location} cannot be an empty string.")
        match = _SCALAR_WITH_OPTIONAL_UNIT_PATTERN.match(token)
        if match is None:
            raise ValueError(
                f"{location} must be numeric or '<number> <unit>' (for example '1.0 m')."
            )
        scalar = float(match.group(1))
        unit_token = match.group(2).strip()
        if unit_token != "":
            inline_unit = unit_token
    else:
        raise TypeError(f"{location} must be numeric or a string like '12.3 m'.")

    resolved_unit = unit_from_field or default_unit_token
    if inline_unit is not None:
        if unit_from_field is not None:
            if _canonical_unit_token(inline_unit) != _canonical_unit_token(unit_from_field):
                raise ValueError(
                    f"{location} mixes conflicting units: '{inline_unit}' and '{unit_from_field}'."
                )
        else:
            resolved_unit = inline_unit
    return scalar, resolved_unit

