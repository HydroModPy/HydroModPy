"""Shared TOML/config helpers used across solver utility modules."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any


def get_nested_section(payload: Mapping[str, Any], dotted_path: str) -> Mapping[str, Any]:
    """Resolve one nested section using dotted syntax (for example ``case.mesh``)."""
    current: Any = payload
    for token in str(dotted_path).split("."):
        if not isinstance(current, Mapping) or token not in current:
            raise KeyError(f"Missing TOML section '{dotted_path}'")
        current = current[token]
    if not isinstance(current, Mapping):
        raise ValueError(f"TOML section '{dotted_path}' must be a mapping")
    return current


def resolve_path(path_value: str | Path, base_dir: Path) -> str:
    """Resolve a possibly-relative path against *base_dir* and return a string."""
    path = Path(str(path_value)).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return str(path)
