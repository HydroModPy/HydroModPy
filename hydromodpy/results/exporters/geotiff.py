"""Export simulation fields to GeoTIFF by rasterizing unstructured meshes."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import zarr

logger = logging.getLogger(__name__)


def export_geotiff(
    zarr_path: str | Path,
    sim_id: str,
    variable: str,
    timestep: int,
    output_path: str | Path,
    *,
    layer: int | None = None,
    resolution: float = 100.0,
    crs: str = "EPSG:2154",
    nodata: float = -9999.0,
) -> Path:
    """Rasterize a field from the unstructured mesh into a GeoTIFF.

    Requires ``rasterio`` and ``shapely``.

    Parameters
    ----------
    zarr_path : str or Path
        Path to the simulation Zarr store.
    sim_id : str
        Simulation UUID.
    variable : str
        Field name.
    timestep : int
        Timestep index.
    output_path : str or Path
        Destination ``.tif`` file.
    layer : int, optional
        Layer index for 3D fields. Defaults to the first layer.
    resolution : float
        Pixel size in CRS units (default 100 m).
    crs : str
        Coordinate reference system (default ``"EPSG:2154"``).
    nodata : float
        NoData value in the output raster.

    Returns
    -------
    Path
        The written file path.
    """
    import rasterio
    from rasterio.features import rasterize
    from rasterio.transform import from_bounds
    from shapely.geometry import Polygon

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    root = zarr.open_group(str(zarr_path), mode="r")
    grp = root
    mesh = grp["mesh"]

    vertices = mesh["vertices"][:]
    connectivity = mesh["face_node_connectivity"][:]

    arr = _find_variable(grp, variable)
    if arr is None:
        raise KeyError(f"Variable '{variable}' not found for sim={sim_id}")

    data = arr[timestep]
    if data.ndim == 2:
        data = data[layer or 0]

    # Build shapely polygons for each cell
    shapes = []
    for i, face in enumerate(connectivity):
        node_ids = face[face >= 0]
        coords = vertices[node_ids, :2]
        if len(coords) < 3:
            continue
        poly = Polygon(coords)
        if poly.is_valid and not poly.is_empty:
            shapes.append((poly, float(data[i])))

    if not shapes:
        raise ValueError("No valid polygons to rasterize")

    # Compute raster bounds from mesh extent
    xmin = float(vertices[:, 0].min())
    ymin = float(vertices[:, 1].min())
    xmax = float(vertices[:, 0].max())
    ymax = float(vertices[:, 1].max())

    width = max(1, int(np.ceil((xmax - xmin) / resolution)))
    height = max(1, int(np.ceil((ymax - ymin) / resolution)))
    transform = from_bounds(xmin, ymin, xmax, ymax, width, height)

    raster = rasterize(
        shapes,
        out_shape=(height, width),
        transform=transform,
        fill=nodata,
        dtype="float64",
    )

    with rasterio.open(
        str(output_path),
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float64",
        crs=crs,
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(raster, 1)

    logger.info("Exported GeoTIFF: %s (%dx%d)", output_path, width, height)
    return output_path


def _find_variable(grp, var_name: str):
    """Search for a variable in the simulation group and its subgroups."""
    if var_name in grp:
        return grp[var_name]
    for sub in ("derived", "budget"):
        sg = grp.get(sub)
        if sg is not None and var_name in sg:
            return sg[var_name]
    return None
