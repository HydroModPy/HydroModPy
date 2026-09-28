"""Export fields and geographic rasters of a run to GeoTIFF.

A field lives on the unstructured mesh and is rasterized; a geographic raster
(the DEM the catchment was cut from, the filled one) is a raster already and
is written as it is, or warped when a CRS or a resolution is asked.

Output rasters honour the OGC Cloud Optimized GeoTIFF (COG) 1.0 spec:
internal tiling at 512x512 and zstd compression. The COG driver builds
overviews at 2/4/8/16/32x only when the image is larger than one tile, so a
small catchment carries none. Each raster carries provenance tags so
consumers can trace back to the source simulation and the period it shows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.results.derive.virtual_fields import field_descriptor
from hydromodpy.results.exporters._fields import native_crs, one_layer, read_field_step
from hydromodpy.results.zarr_store import SimulationZarr

if TYPE_CHECKING:
    from rasterio.enums import Resampling

    from hydromodpy.results.field_registry import FieldDescriptor

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
    values: np.ndarray | None = None,
    period: str | None = None,
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
        Timestep index. Ignored for a static field.
    output_path : str or Path
        Destination ``.tif`` file.
    layer : int, optional
        Layer of a field of several layers. Required when the field holds
        more than one: a GeoTIFF holds one layer.
    resolution : float, optional
        Pixel size in CRS units. Left out, the side of a square of the mean
        cell area.
    crs : str
        Coordinate reference system of the output. When it differs from the
        CRS the mesh is stored in, the raster is reprojected into it.
    nodata : float
        NoData value in the output raster.
    values : numpy.ndarray, optional
        The per-cell values to write, when the caller computed them. The
        store is then read for the mesh only.
    period : str, optional
        The period the values describe (``2002-10``), written in the
        ``HMP_PERIOD`` tag.

    Returns
    -------
    Path
        The written file path.

    Raises
    ------
    ValueError
        Raised when ``crs`` is missing, when the field holds
        several layers and none is given, or when the mesh cannot be
        rasterized.
    KeyError
        Raised when ``variable`` is not stored in the Zarr hierarchy.

    Examples
    --------
    >>> export_geotiff(
    ...     run_zarr, run.sim_id, "head", -1, "head.tif", resolution=25, crs="EPSG:2154"
    ... )  # doctest: +SKIP
    """
    from rasterio.features import rasterize
    from rasterio.transform import from_bounds
    from shapely.geometry import Polygon

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    descriptor = field_descriptor(variable)
    if crs is None:
        raise ValueError("GeoTIFF export requires an explicit CRS.")

    sz = SimulationZarr(zarr_path)
    try:
        grp = sz.root
        mesh = grp["mesh"]
        vertices = mesh["vertices"][:]
        connectivity = mesh["face_node_connectivity"][:]
        source_crs = native_crs(grp)
        data = values if values is not None else read_field_step(sz, sim_id, variable, timestep)
    finally:
        sz.close()
    data = one_layer(data, variable, layer, "GeoTIFF")

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
    if resolution is None:
        resolution = float(np.sqrt(np.mean([poly.area for poly, _ in shapes])))

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

    if source_crs is None:
        # No grid mapping in the store: the caller's CRS is the only statement
        # about where these coordinates are, so tag with it and warp nothing.
        logger.warning(
            "No CRS recorded in the run store: tagging %s as %s without reprojecting.",
            output_path.name,
            crs,
        )
    else:
        raster, transform = _warp(
            raster,
            transform,
            source_crs,
            crs,
            nodata=nodata,
            resampling=_resampling_for(descriptor, data),
        )

    tags = {
        "HMP_SIM_ID": str(sim_id),
        "HMP_VARIABLE": str(variable),
        "HMP_UNITS": descriptor.units,
        "HMP_TIMESTAMP": datetime.now(UTC).isoformat(),
    }
    if period:
        tags["HMP_PERIOD"] = period
    _write_cog(output_path, raster, transform=transform, crs=crs, nodata=nodata, tags=tags)
    logger.info("Exported COG GeoTIFF: %s (%dx%d)", output_path, raster.shape[1], raster.shape[0])
    return output_path


def export_geographic_raster(
    zarr_path: str | Path,
    sim_id: str,
    name: str,
    output_path: str | Path,
    *,
    crs: str | None = None,
    resolution: float | None = None,
) -> Path:
    """Write one geographic raster of a run (``watershed_dem``...) to a GeoTIFF.

    The raster is written on its own grid. ``crs`` reprojects it and
    ``resolution`` resamples it, bilinearly: a DEM is continuous. The nodata
    value is the one the raster was stored with.

    Raises
    ------
    KeyError
        The run stores no raster of that name.
    """
    from rasterio.transform import Affine

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sz = SimulationZarr(zarr_path)
    try:
        data, meta = sz.read_geographic_raster(name)
    finally:
        sz.close()
    raster = np.asarray(data, dtype="float64")
    if raster.ndim == 3:
        raster = raster[0]
    transform = Affine(*tuple(meta["transform"])[:6])
    source_crs = str(meta.get("crs") or "") or None
    nodata = float(meta.get("nodata", -99999.0))
    target_crs = crs or source_crs
    if target_crs is None:
        raise ValueError(f"Geographic raster {name!r} carries no CRS; give crs to tag it.")
    if source_crs is not None and (crs is not None or resolution is not None):
        from rasterio.enums import Resampling

        raster, transform = _warp(
            raster,
            transform,
            source_crs,
            target_crs,
            nodata=nodata,
            resampling=Resampling.bilinear,
            resolution=resolution,
        )
    tags = {
        "HMP_SIM_ID": str(sim_id),
        "HMP_VARIABLE": str(name),
        "HMP_TIMESTAMP": datetime.now(UTC).isoformat(),
    }
    _write_cog(output_path, raster, transform=transform, crs=target_crs, nodata=nodata, tags=tags)
    logger.info("Exported COG GeoTIFF: %s (%dx%d)", output_path, raster.shape[1], raster.shape[0])
    return output_path


def _warp(
    raster: np.ndarray,
    transform: Any,
    source_crs: str,
    target_crs: str,
    *,
    nodata: float,
    resampling: Resampling,
    resolution: float | None = None,
) -> tuple[np.ndarray, Any]:
    """Reproject or resample a raster; return it unchanged when nothing changes."""
    from rasterio.crs import CRS
    from rasterio.transform import array_bounds
    from rasterio.warp import calculate_default_transform, reproject

    same_crs = CRS.from_user_input(target_crs) == CRS.from_user_input(source_crs)
    if same_crs and resolution is None:
        return raster, transform
    height, width = raster.shape
    west, south, east, north = array_bounds(height, width, transform)
    dst_transform, dst_width, dst_height = calculate_default_transform(
        source_crs,
        target_crs,
        width,
        height,
        left=west,
        bottom=south,
        right=east,
        top=north,
        resolution=resolution,
    )
    destination = np.full((dst_height, dst_width), nodata, dtype="float64")
    reproject(
        source=raster,
        destination=destination,
        src_transform=transform,
        src_crs=source_crs,
        src_nodata=nodata,
        dst_transform=dst_transform,
        dst_crs=target_crs,
        dst_nodata=nodata,
        resampling=resampling,
    )
    return destination, dst_transform


def _write_cog(
    output_path: Path,
    raster: np.ndarray,
    *,
    transform: Any,
    crs: str,
    nodata: float,
    tags: dict[str, str],
) -> None:
    """Write one band as a Cloud Optimized GeoTIFF.

    A plain tiled GTiff is written in memory, then the GDAL COG driver
    (>=3.1) produces the final file in one CreateCopy pass. The COG driver
    lays out tiles, overviews and IFDs in the order the spec requires;
    building overviews after a plain GTiff write does not yield a valid COG.
    """
    import rasterio
    import rasterio.shutil
    from rasterio.io import MemoryFile

    height, width = raster.shape
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
            tmp.update_tags(**tags)
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


def _resampling_for(descriptor: FieldDescriptor, values: np.ndarray) -> Resampling:
    """Pick the warp resampling rule for one field.

    The registry carries no categorical flag, so the values decide: a
    dimensionless field made of whole numbers is a mask or a class code
    (``seepage_mask`` is 0/1) and interpolating it would invent classes the
    model never produced, so it takes nearest. Anything else is continuous
    (head in m, a fractional dimensionless field such as porosity) and takes
    bilinear. Unreadable values fall back to nearest, the conservative rule:
    it can only ever repeat a value that is already in the source raster.
    """
    from rasterio.enums import Resampling

    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return Resampling.nearest
    integral = bool(np.all(finite == np.rint(finite)))
    if descriptor.units == "1" and integral:
        return Resampling.nearest
    return Resampling.bilinear
