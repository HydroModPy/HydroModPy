"""Low-level validation helpers for the public mesh visualization TOML."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path


class ValidationError(ValueError):
    """Validation error raised for invalid public TOML input."""


def require_mapping(raw_value: object, *, label: str) -> Mapping[str, object]:
    """Ensure that one TOML block is a key/value table."""

    if not isinstance(raw_value, Mapping):
        raise ValidationError(f"{label} must be a TOML table.")
    return raw_value


def forbid_unknown_keys(
    raw_mapping: Mapping[str, object],
    *,
    allowed_keys: set[str],
    label: str,
) -> None:
    """Reject unknown public keys to keep the contract explicit."""

    unknown_keys = sorted(set(raw_mapping) - allowed_keys)
    if unknown_keys:
        raise ValidationError(f"{label} contains unknown keys: {', '.join(unknown_keys)}.")


def read_mapping_value(
    raw_mapping: Mapping[str, object],
    key: str,
    *,
    default: object,
    parser,
    label: str | None = None,
):
    """Read one TOML key, apply its default value, then apply the parser."""

    value = raw_mapping.get(key, default)
    if label is None:
        return parser(value)
    return parser(value, label=label)


def coerce_required_text(value: object, *, label: str) -> str:
    """Return one required non-empty text field."""

    if value is None:
        raise ValidationError(f"{label} is required.")
    text = str(value).strip()
    if text == "":
        raise ValidationError(f"{label} is required.")
    return text


def coerce_optional_text(value: object | None) -> str | None:
    """Return one stripped optional text field."""

    if value is None:
        return None
    text = str(value).strip()
    return None if text == "" else text


def coerce_path(value: object, *, label: str) -> Path:
    """Return one required path-like field."""

    if value is None:
        raise ValidationError(f"{label} is required.")
    text = str(value).strip()
    if text == "":
        raise ValidationError(f"{label} is required.")
    return Path(text)


def coerce_optional_path(value: object | None) -> Path | None:
    """Return one optional path-like field."""

    if value is None:
        return None
    text = str(value).strip()
    return None if text == "" else Path(text)


def coerce_bool(value: object, *, label: str) -> bool:
    """Parse one public TOML boolean value."""

    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    raise ValidationError(f"{label} must be a boolean.")


def coerce_positive_int(value: object, *, label: str) -> int:
    """Parse one positive integer TOML value."""

    if isinstance(value, bool):
        raise ValidationError(f"{label} must be an integer > 0.")
    try:
        coerced = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be an integer > 0.") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValidationError(f"{label} must be an integer > 0.")
    if coerced <= 0:
        raise ValidationError(f"{label} must be an integer > 0.")
    return coerced


def coerce_non_negative_float(value: object, *, label: str) -> float:
    """Parse one non-negative float TOML value."""

    try:
        coerced = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be a number >= 0.") from exc
    if coerced < 0.0:
        raise ValidationError(f"{label} must be a number >= 0.")
    return coerced


def coerce_figure_size(value: object) -> tuple[float, float]:
    """Parse one ``[width, height]`` TOML figure-size field."""

    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValidationError("figure_size must contain exactly two numbers.")
    if len(value) != 2:
        raise ValidationError("figure_size must contain exactly two numbers.")
    try:
        width = float(value[0])
        height = float(value[1])
    except (TypeError, ValueError) as exc:
        raise ValidationError("figure_size must contain exactly two numbers.") from exc
    if width <= 0.0 or height <= 0.0:
        raise ValidationError("figure_size must contain values > 0.")
    return (width, height)


__all__ = [
    "ValidationError",
    "coerce_bool",
    "coerce_figure_size",
    "coerce_non_negative_float",
    "coerce_optional_path",
    "coerce_optional_text",
    "coerce_path",
    "coerce_positive_int",
    "coerce_required_text",
    "forbid_unknown_keys",
    "read_mapping_value",
    "require_mapping",
]
