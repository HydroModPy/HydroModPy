"""Shared filesystem-safe naming helpers."""

from __future__ import annotations

import re
import unicodedata

_SAFE_CHAR_RE = re.compile(r"[^a-z0-9_-]+")
_COLLAPSE_UNDERSCORE_RE = re.compile(r"_+")

MAX_SEGMENT_LEN = 32
UNNAMED = "unnamed"


def sanitize_segment(value: str | None, *, max_len: int = MAX_SEGMENT_LEN) -> str:
    """Return a filesystem-safe lowercase slug from an arbitrary string."""
    if not value:
        return UNNAMED
    folded = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    slug = _SAFE_CHAR_RE.sub("_", folded.strip().lower())
    slug = _COLLAPSE_UNDERSCORE_RE.sub("_", slug).strip("_-")
    if not slug:
        return UNNAMED
    return slug[:max_len].rstrip("_-") or UNNAMED


__all__ = ["MAX_SEGMENT_LEN", "UNNAMED", "sanitize_segment"]
