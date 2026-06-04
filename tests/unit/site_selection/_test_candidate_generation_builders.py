from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


def write_accumulation_raster(
    path: Path,
    values: np.ndarray,
    *,
    cell_size: float = 10.0,
) -> Path:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype="float64",
        crs="EPSG:2154",
        transform=from_origin(0.0, float(values.shape[0]) * cell_size, cell_size, cell_size),
        nodata=-9999.0,
    ) as dst:
        dst.write(values, 1)
    return path
