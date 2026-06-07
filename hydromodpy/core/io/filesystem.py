"""Filesystem utilities (directory creation, CSV loading)."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


def create_folder(path) -> None:
    """Create directory tree if it does not already exist."""
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def load_csv(file_path: str) -> pd.DataFrame:
    """Load a CSV file into a DataFrame."""
    try:
        return pd.read_csv(file_path)
    except Exception:
        logger.exception("Failed to load CSV file %s", file_path)
        return pd.DataFrame()


def native_io_path(path: Path | str) -> str:
    """Return a filesystem path string suitable for lower-level IO libraries."""
    value = str(Path(path).resolve())
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


__all__ = ["create_folder", "load_csv", "native_io_path"]
