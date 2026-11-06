"""Helpers shared by the two BRGM geology downloads."""

from __future__ import annotations

import hashlib
from pathlib import Path

FGEOL_LAYER_PATTERN = "S_FGEOL_2154"


def bbox_hash(bbox: tuple) -> str:
    """Short deterministic hash of a bounding box, rounded to 2 decimals."""
    s = f"{bbox[0]:.2f}_{bbox[1]:.2f}_{bbox[2]:.2f}_{bbox[3]:.2f}"
    return hashlib.md5(s.encode()).hexdigest()[:8]


def find_fgeol_shp(extract_dir: Path) -> Path | None:
    """Find the S_FGEOL shapefile inside an extracted archive, or None."""
    candidates = list(extract_dir.rglob(f"*{FGEOL_LAYER_PATTERN}.shp"))
    return candidates[0] if candidates else None
