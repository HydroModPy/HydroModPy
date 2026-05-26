"""Repository-level resources used by catchment report rendering."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

GEOLOGY_DATA_ROOT = REPO_ROOT / "examples" / "data" / "geology"
GALLERY_GEO = REPO_ROOT / "docs" / "source" / "_static" / "capability_gallery" / "geographic"
GALLERY_SIM = REPO_ROOT / "docs" / "source" / "_static" / "capability_gallery" / "simulation"

__all__ = [
    "GALLERY_GEO",
    "GALLERY_SIM",
    "GEOLOGY_DATA_ROOT",
    "REPO_ROOT",
]
