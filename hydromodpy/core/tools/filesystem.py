"""Filesystem utilities (directory creation, CSV/shapefile loading)."""

from __future__ import annotations

import os
import logging

import pandas as pd
import geopandas as gpd

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


def load_shapefile(shapefile_path: str) -> gpd.GeoDataFrame | None:
    """Load a shapefile into a GeoDataFrame."""
    try:
        return gpd.read_file(shapefile_path)
    except Exception:
        logger.exception("Failed to load shapefile %s", shapefile_path)
        return None
