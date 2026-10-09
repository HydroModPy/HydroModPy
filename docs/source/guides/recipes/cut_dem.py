"""Cut a DEM of a catchment from the Copernicus GLO-30 tiles, and reproject it.

GLO-30 is a global 30 m surface model, published as one GeoTIFF per degree cell on a
public bucket. The script reads only the window it needs.

    python cut_dem.py 5.28 50.18 5.52 50.36 EPSG:25831 dem_ardennes_25831.tif

The arguments are the west, south, east and north of the box in degrees, the projected
CRS of the project, and the output file. The box must sit inside one tile.
Check the licence of the model before you share a run that used it.
"""

import math
import sys

import numpy as np
import rasterio
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rasterio.windows import bounds as window_bounds
from rasterio.windows import from_bounds

BUCKET = "https://copernicus-dem-30m.s3.amazonaws.com"
RESOLUTION = 30  # m, in the projected CRS
NODATA = -9999.0


def tile_url(west: float, south: float) -> str:
    """Return the URL of the tile that holds the south-west corner."""
    lat, lon = math.floor(south), math.floor(west)
    ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
    name = f"Copernicus_DSM_COG_10_{ns}{abs(lat):02d}_00_{ew}{abs(lon):03d}_00_DEM"
    return f"/vsicurl/{BUCKET}/{name}/{name}.tif"


west, south, east, north = (float(v) for v in sys.argv[1:5])
crs, out = sys.argv[5], sys.argv[6]
if math.floor(east - 1e-9) != math.floor(west) or math.floor(north - 1e-9) != math.floor(south):
    raise SystemExit("The box must sit inside one one-degree tile. Cut two boxes.")

with rasterio.open(tile_url(west, south)) as src:
    window = from_bounds(west, south, east, north, src.transform)
    data = src.read(1, window=window)
    transform = src.window_transform(window)
    new_transform, width, height = calculate_default_transform(
        src.crs,
        crs,
        data.shape[1],
        data.shape[0],
        *window_bounds(window, src.transform),
        resolution=RESOLUTION,
    )
    cut = np.full((height, width), NODATA, dtype="float32")
    reproject(
        data,
        cut,
        src_transform=transform,
        src_crs=src.crs,
        dst_transform=new_transform,
        dst_crs=crs,
        resampling=Resampling.bilinear,
        dst_nodata=NODATA,
    )

profile = {
    "driver": "GTiff",
    "height": height,
    "width": width,
    "count": 1,
    "dtype": "float32",
    "crs": crs,
    "transform": new_transform,
    "nodata": NODATA,
    "compress": "deflate",
}
with rasterio.open(out, "w", **profile) as dst:
    dst.write(cut, 1)
print(f"{out}: {width} x {height} cells of {RESOLUTION} m in {crs}")
