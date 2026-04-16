"""Helpers for path-based calibration overrides written as TOML fragments."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from hydromodpy.simulation.model_calibration_support import (
    parse_numeric_with_optional_suffix,
    resolve_flow_property_config,
)


def split_target_path(target: str) -> tuple[str, ...]:
    """Split one dotted target path into validated segments."""
    parts = tuple(str(token).strip() for token in str(target).split("."))
    if not parts or any(not part for part in parts):
        raise ValueError(f"Invalid empty target path segment in '{target}'")
    return parts


def lookup_nested_value(mapping: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Resolve one dotted target path inside a nested mapping."""
    current: Any = mapping
    current_path: list[str] = []
    for key in path:
        current_path.append(key)
        if not isinstance(current, dict):
            raise KeyError(
                "Cannot descend into non-mapping value at "
                f"{'.'.join(current_path[:-1]) or '<root>'}"
            )
        if key not in current:
            raise KeyError(f"Missing target path '{'.'.join(current_path)}'")
        current = current[key]
    return current


def assign_nested_value(mapping: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    """Assign one value inside a nested mapping, creating intermediate dicts."""
    current = mapping
    for key in path[:-1]:
        existing = current.get(key)
        if existing is None:
            current[key] = {}
            existing = current[key]
        elif not isinstance(existing, dict):
            raise ValueError(
                f"Cannot create nested path under non-mapping key '{key}'"
            )
        current = existing
    current[path[-1]] = value


def _path_exists(mapping: dict[str, Any], path: tuple[str, ...]) -> bool:
    """Return True when one nested path exists in a mapping payload."""
    current: Any = mapping
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]
    return True


def resolve_target_path_alias(
    mapping: dict[str, Any],
    path: tuple[str, ...],
) -> tuple[str, ...]:
    """Resolve user-facing calibration targets to the raw TOML payload path."""
    if len(path) < 4 or path[0] != "flow" or path[1] != "param":
        return path

    property_name = path[2]
    property_cfg = resolve_flow_property_config(
        raw_simulation_toml=mapping,
        property_name=property_name,
    )
    if property_cfg is None:
        return path

    leaf = path[3]
    if leaf == "value":
        candidate = (
            "flow",
            "param",
            property_name,
            "field_homogeneous",
            "value",
            *path[4:],
        )
        if _path_exists(mapping, candidate):
            return candidate
    if leaf == "values_by_key":
        candidate = (
            "flow",
            "param",
            property_name,
            "field_heterogeneous",
            "values",
            *path[4:],
        )
        if _path_exists(mapping, candidate):
            return candidate
    if leaf == "field_spatial_id":
        candidate = (
            "flow",
            "param",
            property_name,
            "field_heterogeneous",
            "field_spatial_id",
            *path[4:],
        )
        if _path_exists(mapping, candidate):
            return candidate
    return path


def _format_numeric_like(value: float, *, suffix: str | None) -> Any:
    """Format one numeric value, optionally preserving a unit suffix."""
    number_text = format(float(value), ".12g")
    if suffix is None or suffix == "":
        return float(number_text)
    return f"{number_text} {suffix}"


def apply_parameter_override(
    *,
    base_value: Any,
    candidate_value: float,
    mode: str,
) -> Any:
    """Apply one calibrated candidate value onto the current target payload."""
    parsed = parse_numeric_with_optional_suffix(base_value)
    if parsed is None:
        raise TypeError(
            "Path-based parameter injection currently supports only numeric "
            "targets or numeric strings with optional unit suffixes"
        )
    base_number, suffix = parsed
    candidate_number = float(candidate_value)

    if mode == "replace":
        return _format_numeric_like(candidate_number, suffix=suffix)
    if mode == "scale":
        return _format_numeric_like(base_number * candidate_number, suffix=suffix)
    raise ValueError(f"Unsupported parameter injection mode '{mode}'")


def _format_toml_scalar(value: Any) -> str:
    """Format one supported scalar as a TOML literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("TOML writer does not support NaN/Inf values")
        return format(value, ".12g")
    if isinstance(value, Path):
        return json.dumps(str(value), ensure_ascii=True)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_format_toml_scalar(item) for item in value) + "]"
    raise TypeError(f"Unsupported TOML scalar value: {type(value)!r}")


def _render_toml_mapping(
    mapping: dict[str, Any],
    *,
    prefix: tuple[str, ...] = (),
) -> list[str]:
    """Render a nested mapping into a minimal TOML document."""
    lines: list[str] = []
    scalars: list[tuple[str, Any]] = []
    subtables: list[tuple[str, dict[str, Any]]] = []

    for key, value in mapping.items():
        if isinstance(value, dict):
            subtables.append((str(key), value))
        else:
            scalars.append((str(key), value))

    if prefix:
        lines.append(f"[{'.'.join(prefix)}]")
    for key, value in scalars:
        lines.append(f"{key} = {_format_toml_scalar(value)}")
    if prefix and (scalars or subtables):
        lines.append("")

    for key, value in subtables:
        lines.extend(_render_toml_mapping(value, prefix=(*prefix, key)))

    return lines


def write_override_toml(path: Path, payload: dict[str, Any]) -> None:
    """Write one minimal override TOML payload to disk."""
    lines = _render_toml_mapping(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


__all__ = [
    "apply_parameter_override",
    "assign_nested_value",
    "lookup_nested_value",
    "resolve_target_path_alias",
    "split_target_path",
    "write_override_toml",
]
