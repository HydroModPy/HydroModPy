"""Repository-level resources used by catchment report rendering."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

GEOLOGY_DATA_ROOT = REPO_ROOT / "examples" / "data" / "geology"

__all__ = [
    "GEOLOGY_DATA_ROOT",
    "REPO_ROOT",
]
