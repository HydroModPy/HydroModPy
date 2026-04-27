"""Helpers to resolve config-declared paths consistently across platforms."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def is_declared_absolute_path(path: Path) -> bool:
    """Return True for absolute paths, including drive-less rooted paths."""
    if path.is_absolute():
        return True
    return path.drive == "" and path.root in {"/", "\\"}


def _is_bare_filename(path: Path) -> bool:
    """True when ``path`` has no separator and no ``..`` traversal."""
    parts = path.parts
    if len(parts) != 1:
        return False
    if parts[0] in ("", ".", ".."):
        return False
    return True


def resolve_declared_path(
    raw_value: str | Path,
    *,
    base_dir: Path,
    fallback_dirs: Iterable[Path] | None = None,
) -> Path:
    """Resolve one config path against ``base_dir`` (or a fallback dir).

    Resolution order:

    1. Absolute paths (including ``~``) are returned as-is.
    2. Paths that contain a separator or a ``..`` segment are resolved
       against ``base_dir`` (legacy behaviour).
    3. Bare filenames (e.g. ``"etp_sim2.nc"``) are looked up against
       ``base_dir`` first, then each ``fallback_dirs`` entry. The first
       existing match wins. If nothing exists yet (the file may be
       generated later), the ``base_dir`` resolution is returned so the
       error message stays predictable.
    """
    path = Path(raw_value).expanduser()
    if is_declared_absolute_path(path):
        return path

    primary = (base_dir / path).resolve()
    if not _is_bare_filename(path) or fallback_dirs is None:
        return primary

    if primary.exists():
        return primary
    for candidate_dir in fallback_dirs:
        if candidate_dir is None:
            continue
        candidate = (Path(candidate_dir) / path).resolve()
        if candidate.exists():
            return candidate
    return primary
