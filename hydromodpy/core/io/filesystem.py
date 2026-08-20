"""Filesystem utilities (directory creation, CSV loading)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    import pandas as pd

logger = get_logger(__name__)


def create_folder(path) -> None:
    """Create directory tree if it does not already exist."""
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def load_csv(file_path: str) -> pd.DataFrame:
    """Load a CSV file into a DataFrame."""
    # Lazy: native_io_path puts this module on the migration boot path, and a
    # top-level pandas import would cost every command half a second there.
    import pandas as pandas_module

    try:
        return pandas_module.read_csv(file_path)
    except Exception:
        logger.exception("Failed to load CSV file %s", file_path)
        return pandas_module.DataFrame()


def native_io_path(path: Path | str) -> str:
    """Return a filesystem path string suitable for lower-level IO libraries."""
    value = str(Path(path).resolve())
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


__all__ = ["create_folder", "load_csv", "native_io_path"]
