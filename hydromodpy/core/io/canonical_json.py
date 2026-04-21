"""Deterministic JSON serialization.

Stable output across Python versions and runs: sorted keys at every level,
no whitespace noise, sets promoted to sorted lists, tuples rendered as
arrays. Used by calibration caches, provenance manifests, and any place
that needs a reproducible byte representation of a Python object.
"""

from __future__ import annotations

import json
from typing import Any


def _normalize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _normalize(obj[k]) for k in sorted(obj, key=str)}
    if isinstance(obj, (set, frozenset)):
        return [_normalize(v) for v in sorted(obj, key=repr)]
    if isinstance(obj, tuple):
        return [_normalize(v) for v in obj]
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    return obj


def dumps(obj: Any, *, indent: int | None = None) -> str:
    """Serialize *obj* to a canonical JSON string."""
    return json.dumps(
        _normalize(obj),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":") if indent is None else (",", ": "),
        indent=indent,
    )


def loads(text: str) -> Any:
    """Parse a JSON string (thin wrapper around :func:`json.loads`)."""
    return json.loads(text)


__all__ = ["dumps", "loads"]
