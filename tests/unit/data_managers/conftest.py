"""Shared fixtures for data_managers tests."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Return a temporary directory pre-populated with sample custom data."""
    return tmp_path


@pytest.fixture
def sample_hydro_dir(tmp_path):
    """Temporary directory with hydrometry custom files (LOC + 2 chronicles)."""
    d = tmp_path / "hydro"
    d.mkdir()

    pd.DataFrame({
        "id": ["ST001", "ST002"],
        "x": [-1.5, -1.6],
        "y": [48.1, 48.2],
        "crs": ["EPSG:4326", "EPSG:4326"],
        "unit": ["m3/s", "m3/s"],
    }).to_csv(d / "hydrometry_custom_LOC.csv", index=False)

    dates = pd.date_range("2020-01-01", "2020-03-31", freq="D")
    for sid, val in [("ST001", 2.5), ("ST002", 5.0)]:
        pd.DataFrame({
            "datetime": dates,
            "value": val,
        }).to_csv(d / f"hydrometry_custom_{sid}_20200101_20200331_D.csv", index=False)

    return d


@pytest.fixture
def sample_piezo_dir(tmp_path):
    """Temporary directory with piezometry custom files."""
    d = tmp_path / "piezo"
    d.mkdir()

    pd.DataFrame({
        "id": ["BSS001", "BSS002"],
        "x": [-1.5, -1.6],
        "y": [48.1, 48.2],
        "crs": ["EPSG:4326", "EPSG:4326"],
        "unit": ["m", "m"],
    }).to_csv(d / "piezometry_custom_LOC.csv", index=False)

    dates = pd.date_range("2020-01-01", "2020-03-31", freq="D")
    for sid, val in [("BSS001", 15.0), ("BSS002", 22.5)]:
        pd.DataFrame({
            "datetime": dates,
            "value": val,
        }).to_csv(d / f"piezometry_custom_{sid}_20200101_20200331_D.csv", index=False)

    return d


@pytest.fixture
def sample_wq_dir(tmp_path):
    """Temporary directory with water quality custom files."""
    d = tmp_path / "wq"
    d.mkdir()

    pd.DataFrame({
        "id": ["SITE01", "SITE02"],
        "x": [2.35, 2.40],
        "y": [48.85, 48.90],
        "crs": ["EPSG:4326", "EPSG:4326"],
        "unit": ["mg/L", "mg/L"],
    }).to_csv(d / "waterquality_custom_LOC.csv", index=False)

    dates = pd.date_range("2020-01-01", "2020-03-31", freq="D")
    for sid, val in [("SITE01", 7.2), ("SITE02", 6.8)]:
        pd.DataFrame({
            "datetime": dates,
            "value": val,
        }).to_csv(d / f"waterquality_custom_{sid}_20200101_20200331_D.csv", index=False)

    return d


@pytest.fixture
def project_period():
    return (datetime(2020, 1, 1), datetime(2020, 3, 31))
