"""Shared config parsing helpers for analysis workflows."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any


def require_mapping(value: object, *, label: str) -> Mapping[str, Any]:
    """Validate that one raw value is a mapping."""
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def normalize_mapping(value: object, *, label: str) -> dict[str, Any]:
    """Return a plain dict from an optional mapping value."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return dict(value)


def require_text(value: object, *, label: str) -> str:
    """Return one normalized non-empty text value."""
    text = "" if value is None else str(value).strip()
    if text == "":
        raise ValueError(f"{label} cannot be empty")
    return text


def optional_text(value: object) -> str | None:
    """Return one normalized optional text value."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_text_list(value: object, *, label: str) -> tuple[str, ...]:
    """Normalize one optional list of distinct text values."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    out: list[str] = []
    seen: set[str] = set()
    for raw_item in value:
        item = str(raw_item).strip()
        if item == "":
            raise ValueError(f"{label} cannot contain empty values")
        normalized = item.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(item)
    return tuple(out)


def normalize_text_mapping(value: object, *, label: str) -> tuple[tuple[str, str], ...]:
    """Normalize one optional mapping of text keys and values."""
    if value is None:
        return ()
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    out: list[tuple[str, str]] = []
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        mapped_value = str(raw_value).strip()
        if key == "":
            raise ValueError(f"{label} cannot contain empty keys")
        if mapped_value == "":
            raise ValueError(f"{label}[{key}] cannot be empty")
        out.append((key, mapped_value))
    out.sort(key=lambda item: item[0].lower())
    return tuple(out)


def resolve_optional_path(base_dir: Path, raw_path: object) -> Path | None:
    """Resolve one optional path relative to the configuration file."""
    text = optional_text(raw_path)
    if text is None:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def resolve_required_path(base_dir: Path, raw_path: object, *, label: str) -> Path:
    """Resolve one required path relative to the configuration file."""
    text = require_text(raw_path, label=label)
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def validate_optional_positive_int(value: object, *, label: str) -> int | None:
    """Validate one optional positive integer."""
    if value is None:
        return None
    out = int(value)
    if out <= 0:
        raise ValueError(f"{label} must be >= 1")
    return out


__all__ = [
    "normalize_mapping",
    "normalize_text_list",
    "normalize_text_mapping",
    "optional_text",
    "require_mapping",
    "require_text",
    "resolve_optional_path",
    "resolve_required_path",
    "validate_optional_positive_int",
]
