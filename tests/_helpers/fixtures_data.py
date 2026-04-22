"""Synthetic data fixtures for the test suite.

Procedural builders for small DEM rasters, synthetic piezometric time
series and synthetic catchment polygons. All helpers are pure and
deterministic; no I/O is performed until a test explicitly writes the
returned objects.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest


def synthetic_dem(nx: int = 20, ny: int = 20, *, amplitude: float = 100.0) -> np.ndarray:
    """Return a cone-shaped DEM centered on the domain, peak=``amplitude``."""
    x = np.arange(nx, dtype=float)
    y = np.arange(ny, dtype=float)
    xv, yv = np.meshgrid(x, y, indexing="xy")
    cx, cy = (nx - 1) / 2.0, (ny - 1) / 2.0
    r = np.hypot(xv - cx, yv - cy)
    r_max = max(r.max(), 1.0)
    return float(amplitude) * (1.0 - r / r_max)


def synthetic_timeseries(
    n_days: int = 30,
    *,
    start: str = "2020-01-01",
    seed: int = 0,
    loc: float = 10.0,
    scale: float = 0.1,
) -> pd.Series:
    """Return a daily AR(1)-like noisy head series."""
    rng = np.random.default_rng(seed)
    index = pd.date_range(start, periods=n_days, freq="D")
    noise = rng.standard_normal(n_days) * float(scale)
    trend = np.linspace(0.0, float(scale) * 2.0, n_days)
    return pd.Series(float(loc) + trend + noise, index=index, name="head")


def synthetic_catchment_polygon() -> dict:
    """Return a synthetic GeoJSON-like catchment (unit square, EPSG:2154)."""
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:2154"}},
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "synthetic", "area_m2": 1.0},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
                },
            }
        ],
    }


@pytest.fixture
def small_dem() -> np.ndarray:
    """Cheap 20x20 synthetic DEM for unit-tier raster tests."""
    return synthetic_dem(nx=20, ny=20)


@pytest.fixture
def ten_day_head_series() -> pd.Series:
    """Ten-day synthetic head time series."""
    return synthetic_timeseries(n_days=10)


@pytest.fixture
def synthetic_today() -> datetime:
    """Frozen reference timestamp used across deterministic tests."""
    return datetime(2024, 1, 1, 0, 0, 0)
