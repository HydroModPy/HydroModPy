"""Regenerate the committed synthetic Cheze-style SFR fixture.

A V-shaped tilted valley draining west to one outlet, with a small reservoir
polygon at the low end of the valley. WhiteboxTools D8 on this DEM yields a
clean dendritic stream network converging into the reservoir. Run from the repo
root: ``python tests/data/sfr_cheze/make_fixture.py``.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

HERE = Path(__file__).parent

CRS = "EPSG:2154"
RES = 25.0
N = 100
X0 = 300_000.0
Y_NORTH = 6_702_500.0
# Valley axis pinned on a CELL CENTER (row 49) so the D8 valley floor is a
# single unambiguous row, not a two-row tie that fragments the stream links.
Y_CENTER = Y_NORTH - 49.5 * RES

# Valley: base + west-east tilt + V-shaped cross-slope towards the axis.
BASE = 90.0
SLOPE_X = 0.02
SLOPE_V = 0.015

# Reservoir polygon at the low (west) end of the valley axis.
LAKE_WEST = X0 + 3 * RES
LAKE_EAST = X0 + 11 * RES
LAKE_HALF_WIDTH = 4 * RES

# Catchment outlet, on the valley axis just west of the reservoir.
OUTLET_X = X0 + 1.5 * RES
OUTLET_Y = Y_CENTER


def write_dem() -> Path:
    xs = X0 + (np.arange(N) + 0.5) * RES
    ys = Y_NORTH - (np.arange(N) + 0.5) * RES
    xx, yy = np.meshgrid(xs, ys)
    dem = BASE + SLOPE_X * (xx - X0) + SLOPE_V * np.abs(yy - Y_CENTER)
    path = HERE / "dem_valley.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=N,
        width=N,
        count=1,
        dtype="float32",
        crs=CRS,
        transform=from_origin(X0, Y_NORTH, RES, RES),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(dem.astype("float32"), 1)
    return path


def write_lake_geometry() -> Path:
    polygon = box(LAKE_WEST, Y_CENTER - LAKE_HALF_WIDTH, LAKE_EAST, Y_CENTER + LAKE_HALF_WIDTH)
    gdf = gpd.GeoDataFrame({"lake_id": ["res0"]}, geometry=[polygon], crs=CRS)
    path = HERE / "lake_geometry.gpkg"
    gdf.to_file(str(path), driver="GPKG")
    return path


def write_lake_abacus() -> Path:
    # DEM under the reservoir spans ~91.9-95.5 m; the abacus brackets it.
    area = (LAKE_EAST - LAKE_WEST) * 2 * LAKE_HALF_WIDTH
    rows = ["stage,volume,sarea"]
    for stage in (91.0, 93.0, 95.0, 97.0, 99.0):
        volume = max(stage - 91.0, 0.0) * area
        rows.append(f"{stage},{volume},{area}")
    path = HERE / "lake_abacus.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_dem())
    print(write_lake_geometry())
    print(write_lake_abacus())
    print(f"outlet: x={OUTLET_X}, y={OUTLET_Y}")
