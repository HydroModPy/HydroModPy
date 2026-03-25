"""Helpers to resolve config-declared paths consistently across platforms."""

from __future__ import annotations

from pathlib import Path


def is_declared_absolute_path(path: Path) -> bool:
    """Return True for absolute paths, including drive-less rooted paths."""
    if path.is_absolute():
        return True
    return path.drive == "" and path.root in {"/", "\\"}


def resolve_declared_path(raw_value: str | Path, *, base_dir: Path) -> Path:
    """Resolve one config path relative to ``base_dir`` when needed."""
    path = Path(raw_value).expanduser()
    if is_declared_absolute_path(path):
        return path
    return (base_dir / path).resolve()
