"""TOML loading helpers with optional hierarchical ``base_config`` support."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
import re
from typing import Any

from hydromodpy.config.path_resolution import is_declared_absolute_path


_BASIC_STRING_ASSIGNMENT_RE = re.compile(
    r'^(?P<prefix>\s*[^#=\n]+?=\s*)"(?P<value>[^"\n]*)"(?P<suffix>\s*(?:#.*)?)$'
)


def _read_toml(path: Path) -> dict[str, Any]:
    """Read one TOML file and return its raw mapping."""
    raw_text = path.read_text(encoding="utf-8-sig")
    try:
        return tomllib.loads(raw_text)
    except tomllib.TOMLDecodeError:
        repaired_text = _repair_path_like_basic_strings(raw_text)
        if repaired_text == raw_text:
            raise
        return tomllib.loads(repaired_text)


def _looks_like_path_key(key: str) -> bool:
    token = str(key).strip().strip("'\"").split(".")[-1].lower()
    if token == "base_config":
        return True
    return any(
        hint in token
        for hint in ("path", "root", "dir", "folder", "file", "mask")
    )


def _repair_path_like_basic_strings(text: str) -> str:
    repaired_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        newline = ""
        if line.endswith("\r\n"):
            line_body = line[:-2]
            newline = "\r\n"
        elif line.endswith("\n"):
            line_body = line[:-1]
            newline = "\n"
        else:
            line_body = line
        match = _BASIC_STRING_ASSIGNMENT_RE.match(line_body)
        if match is None:
            repaired_lines.append(line)
            continue
        prefix = match.group("prefix")
        key = prefix.split("=", 1)[0].strip()
        value = match.group("value")
        if ("\\" not in value) or (not _looks_like_path_key(key)):
            repaired_lines.append(line)
            continue
        repaired_value = value.replace("\\", "\\\\")
        repaired_lines.append(
            f'{prefix}"{repaired_value}"{match.group("suffix")}{newline}'
        )
    return "".join(repaired_lines)


def merge_toml_payloads(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> dict[str, Any]:
    """Recursively merge two TOML payloads.

    Nested mappings are merged key-by-key. Lists of equal-length mappings are
    merged item-by-item so callers can override fields inside array-of-table
    payloads without rewriting every item. All other override values replace
    the base payload as-is.
    """
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = merge_toml_payloads(existing, value)
        elif (
            isinstance(existing, list)
            and isinstance(value, list)
            and len(existing) == len(value)
            and all(isinstance(item, Mapping) for item in existing)
            and all(isinstance(item, Mapping) for item in value)
        ):
            merged[key] = [
                merge_toml_payloads(base_item, override_item)
                for base_item, override_item in zip(existing, value, strict=True)
            ]
        elif isinstance(value, list):
            merged[key] = list(value)
        else:
            merged[key] = value
    return merged


def _strip_empty_strings(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively remove keys whose value is the empty string ``""``.

    Empty strings cannot represent ``None`` in TOML (no native null), so the
    auto-generated templates emit ``key = ""`` as a placeholder for optional
    fields.  Stripping them before Pydantic validation lets the model fall
    back to ``default=None``, which is the intended semantics.

    Only plain ``""`` values on leaf keys are affected -- non-empty strings,
    nested dicts, and lists are traversed but never removed.
    """
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            cleaned[key] = _strip_empty_strings(value)
        elif isinstance(value, list):
            cleaned[key] = [
                _strip_empty_strings(item) if isinstance(item, dict) else item
                for item in value
            ]
        elif value == "":
            continue  # drop empty-string placeholders
        else:
            cleaned[key] = value
    return cleaned


def load_toml_with_base_config(
    toml_path: str | Path,
    *,
    _stack: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Load one TOML file with recursive ``base_config`` inheritance."""
    resolved = Path(toml_path).resolve()
    if resolved in _stack:
        cycle = " -> ".join(str(path) for path in (*_stack, resolved))
        raise ValueError(f"Detected circular base_config chain: {cycle}")

    raw = _read_toml(resolved)
    base_config_name = raw.get("base_config")
    current = dict(raw)
    current.pop("base_config", None)

    if base_config_name in (None, ""):
        return _strip_empty_strings(current)
    if not isinstance(base_config_name, str):
        raise TypeError("base_config must be a TOML string path when provided")

    base_path = Path(base_config_name).expanduser()
    if not is_declared_absolute_path(base_path):
        base_path = (resolved.parent / base_path).resolve()

    base_payload = load_toml_with_base_config(base_path, _stack=(*_stack, resolved))
    return _strip_empty_strings(merge_toml_payloads(base_payload, current))
