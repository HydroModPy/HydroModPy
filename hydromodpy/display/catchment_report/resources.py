"""Repository-level resources used by catchment report rendering."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

__all__ = [
    "REPO_ROOT",
]
