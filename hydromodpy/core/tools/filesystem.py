"""Filesystem utilities (directory creation, CSV loading)."""

from __future__ import annotations

import os
import logging

import pandas as pd

logger = logging.getLogger(__name__)


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
