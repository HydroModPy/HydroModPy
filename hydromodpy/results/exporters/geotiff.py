"""Export simulation fields to GeoTIFF by rasterizing unstructured meshes.

Output rasters honour the OGC Cloud Optimized GeoTIFF (COG) 1.0 spec:
internal tiling at 512x512, zstd compression, and pre-computed overviews
at 2/4/8/16/32x. Each raster carries provenance tags so consumers can
trace back to the source simulation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.results import field_registry
from hydromodpy.results.zarr_store import SimulationZarr

logger = get_logger(__name__)

_COG_TILE = 512
_COG_ZSTD_LEVEL = 5


def export_geotiff(
    zarr_path: str | Path,
    sim_id: str,
    variable: str,
    timestep: int,
    output_path: str | Path,
    *,
    layer: int | None = None,
    resolution: float | None = None,
    crs: str | None = None,
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
        Pixel size in CRS units.
    crs : str
        Coordinate reference system.
    nodata : float
        NoData value in the output raster.

    Returns
    -------
    Path
        The written file path.

    Raises
    ------
    ValueError
        Raised when ``resolution`` or ``crs`` is missing, or when the mesh
        cannot be rasterized.
    KeyError
        Raised when ``variable`` is not stored in the Zarr hierarchy.

    Examples
    --------
    >>> export_geotiff(
    ...     run_zarr, run.sim_id, "head", -1, "head.tif", resolution=25, crs="EPSG:2154"
    ... )
    """
    import rasterio
    import rasterio.shutil
    from rasterio.features import rasterize
    from rasterio.io import MemoryFile
    from rasterio.transform import from_bounds
    from shapely.geometry import Polygon

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    descriptor = field_registry.get(variable)
    if resolution is None:
        raise ValueError("GeoTIFF export requires an explicit resolution.")
    if crs is None:
        raise ValueError("GeoTIFF export requires an explicit CRS.")

    sz = SimulationZarr(zarr_path)
    try:
        grp = sz.root
        mesh = grp["mesh"]
        vertices = mesh["vertices"][:]
        connectivity = mesh["face_node_connectivity"][:]

        arr = _resolve_zarr_path(grp, descriptor.zarr_path)
        if arr is None:
            raise KeyError(
                f"Variable '{variable}' (zarr_path={descriptor.zarr_path!r}) "
                f"not found for sim={sim_id}"
            )
        data = arr[timestep]
    finally:
        sz.close()
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

    # Write a plain tiled GTiff in memory, then let the GDAL COG driver
    # (>=3.1) produce the final file in one CreateCopy pass. The COG driver
    # lays out tiles, overviews and IFDs in the spec-required order; building
    # overviews after a plain GTiff write (the previous approach) does NOT
    # yield a valid COG and would fail `rio cogeo validate`.
    with MemoryFile() as memfile:
        with memfile.open(
            driver="GTiff",
            height=height,
            width=width,
            count=1,
            dtype="float64",
            crs=crs,
            transform=transform,
            nodata=nodata,
        ) as tmp:
            tmp.write(raster, 1)
            tmp.update_tags(
                HMP_SIM_ID=str(sim_id),
                HMP_VARIABLE=str(variable),
                HMP_TIMESTAMP=datetime.now(UTC).isoformat(),
            )
        rasterio.shutil.copy(
            memfile.name,
            str(output_path),
            driver="COG",
            compress="ZSTD",
            level=_COG_ZSTD_LEVEL,
            predictor="YES",
            blocksize=_COG_TILE,
            overview_resampling="AVERAGE",
        )

    logger.info("Exported COG GeoTIFF: %s (%dx%d)", output_path, width, height)
    return output_path


def _resolve_zarr_path(grp, zarr_path: str):
    """Resolve a registry zarr_path inside the simulation group, or None if absent."""
    parts = zarr_path.split("/")
    cursor = grp
    for part in parts[:-1]:
        sub = cursor.get(part)
        if sub is None:
            return None
        cursor = sub
    leaf = parts[-1]
    if leaf in cursor:
        return cursor[leaf]
    return None
