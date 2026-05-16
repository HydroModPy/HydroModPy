"""CF v85 standard-name validation against the bundled curated list."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_TABLE_PATH = Path(__file__).resolve().parent / "data" / "cf_standard_names_v85.txt"


@lru_cache(maxsize=1)
def _cf_v85_names() -> frozenset[str]:
    """Load and cache the curated CF v85 standard names from disk."""
    names: set[str] = set()
    for line in _TABLE_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        names.add(stripped)
    return frozenset(names)


def is_cf_standard_name(name: str) -> bool:
    """Return ``True`` when ``name`` belongs to the bundled CF v85 list.

    The list is a curated subset of CF v85, vendored under
    ``hydromodpy/results/zarr_store/data/cf_standard_names_v85.txt``. A
    full XML vendoring is queued for V2; until then, the curated text
    file covers the standard names actually used by the field registry.
    """
    if not name:
        return False
    return name in _cf_v85_names()


def cf_v85_names() -> frozenset[str]:
    """Return the immutable set of CF v85 names recognised by V1."""
    return _cf_v85_names()


__all__ = ["cf_v85_names", "is_cf_standard_name"]
