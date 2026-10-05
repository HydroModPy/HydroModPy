"""French IGN DEM archive discovery through Geoplateforme.

``fetch_ign_dem`` builds one GeoTIFF from an extent in Lambert-93. BD ALTI 25 m
comes from the department archives, which are downloaded, extracted and merged.
RGE ALTI (1 m or 5 m) comes from the WMS-Raster service, tile by tile, because
its archives are fragmented and far too large to fetch for a catchment.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import requests
from filelock import FileLock

from hydromodpy.core import progress
from hydromodpy.core.io.atomic_replace import staged_path
from hydromodpy.core.logging import get_logger
from hydromodpy.data.variables.dem.apis import geoplateforme_wms as wms
from hydromodpy.data.variables.dem.apis.geoplateforme_download import (
    DiscoveryFilters,
    DownloadFile,
    GeoPlateformeDownloadError,
    RateLimiter,
    build_download_url,
    download_file,
    list_files,
    list_subresources,
)
from hydromodpy.data.variables.dem.config import RGE_ALTI_RESOLUTIONS_M

logger = get_logger(__name__)

IgnDemDataset = Literal["bd-alti", "rge-alti"]

DATASET_RESOURCE_NAMES: dict[str, str] = {
    "bd-alti": "BDALTI",
    "rge-alti": "RGEALTI",
}

RGE_ALTI_WMS_LAYER = "ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES"
# Resolutions come from config.RGE_ALTI_RESOLUTIONS_M. The 1 m grid is the native
# one. Inland, a 5 m request returns, bit for bit, the 1 m value of the pixel that
# holds the 5 m pixel centre (measured 2026-10-05 on a 200 m window, 40 x 40 pixels,
# maximum difference 0.0). Next to water and nodata the server blends, so a few
# pixels differ there (see ``mask_rge_alti``). Any other size is resampled by the
# server with a kernel that is neither that pick nor the block mean (2 m to 25 m
# differed from both by 0.3 to 1.6 m over the same window), so it is refused.
RGE_ALTI_WATER_M = -5.0
# The product writes tidal water and harbour basins as a flat -5 m, which is not a
# terrain height. The server also blends its -99999 nodata into the land next to
# it, giving values far below -5. Real land below -5 m exists (quarries, pits), so
# the mask follows the water and the nodata, never a global threshold.
RGE_ALTI_BLEND_REACH_PX = 3
"""How far from nodata or water the server's blend of nodata reaches, in pixels."""
RGE_ALTI_PROCESSING_VERSION = "rge_alti_mask_v2"
"""Part of the cache request: a raster masked by an older rule is not reused."""
RGE_ALTI_BORDER_BUFFER_M = 1000.0
"""Department outlines stop short of the shore; this keeps the coast inside them."""
RGE_ALTI_FOREIGN_WARN_SHARE = 0.01
_MASK_HALO_PX = RGE_ALTI_BLEND_REACH_PX + 1
_STRIP_ROWS = 1024
RGE_ALTI_DEFAULT_RESOLUTION_M = 5.0
RGE_ALTI_MAX_PIXELS = 150_000_000
"""Largest raster a request may assemble.

At 4 bytes a pixel this is 600 MB before compression, about 25 tiles of 2500 x 2500
pixels and a few minutes of download (7 s for 25 million pixels was measured). It
lets the 60 km bootstrap box of the geographic pipeline through at 5 m (144 million
pixels) and stops a 1 m request above about 12 km a side (a 30 km box at 1 m is 900
million pixels, 3.6 GB), which no later step could route or mesh anyway.
"""


def normalize_department_code(value: str) -> str:
    """Normalize a French department code to the Geoplateforme ``Dxxx`` form."""
    from hydromodpy.spatial.administrative.france import department_code_to_padded

    text = str(value).strip().upper()
    if text.startswith("D"):
        text = text[1:]
    return f"D{department_code_to_padded(text)}"


def discover_ign_dem_files(
    *,
    departments: Sequence[str],
    dataset: IgnDemDataset,
    resolution_m: float | None = None,
    file_format: str = "ASC",
    crs: str | None = None,
    session: requests.Session | None = None,
    timeout: float = 30.0,
    rate_limiter: RateLimiter | None = None,
    allow_static_bdalti_fallback: bool = True,
) -> list[DownloadFile]:
    """Discover downloadable IGN DEM archives for departments.

    Geoplateforme discovery is attempted first. For BD ALTI 25 m ASC only, the
    optional fallback uses HydroModPy's internal archive index to keep the
    assembled raster path usable while provider-side discovery is incomplete.
    """

    resource_name = _resource_name(dataset)
    files: list[DownloadFile] = []
    discovery_failed = False
    for department in [normalize_department_code(value) for value in departments]:
        filters = DiscoveryFilters(
            zone=department,
            file_format=file_format.upper(),
            crs=crs,
        )
        department_files: list[DownloadFile] = []
        if not discovery_failed:
            try:
                department_files = _discover_department_files(
                    resource_name=resource_name,
                    department=department,
                    dataset=dataset,
                    resolution_m=resolution_m,
                    file_format=file_format,
                    filters=filters,
                    session=session,
                    timeout=timeout,
                    rate_limiter=rate_limiter,
                )
            except GeoPlateformeDownloadError:
                discovery_failed = True
        if not department_files and allow_static_bdalti_fallback and dataset == "bd-alti":
            department_files = _bdalti_archive_index_fallback_files(
                department=department,
                resolution_m=resolution_m,
                file_format=file_format,
            )
        files.extend(department_files)
    return files


def download_ign_dem_departments(
    *,
    output_dir: str | Path,
    departments: Sequence[str],
    dataset: IgnDemDataset,
    resolution_m: float | None = None,
    file_format: str = "ASC",
    crs: str | None = None,
    dry_run: bool = False,
    max_files: int | None = None,
    timeout: float = 120.0,
    requests_per_second: float = 8.0,
    overwrite: bool = False,
    session: requests.Session | None = None,
) -> list[Path]:
    """Download or list IGN DEM department archives."""

    limiter = RateLimiter(requests_per_second=requests_per_second)
    files = discover_ign_dem_files(
        departments=departments,
        dataset=dataset,
        resolution_m=resolution_m,
        file_format=file_format,
        crs=crs,
        session=session,
        timeout=min(timeout, 30.0),
        rate_limiter=limiter,
    )
    if max_files is not None:
        files = files[:max_files]

    paths: list[Path] = []
    for file in progress.track(files, "Downloading IGN DEM archives"):
        destination = _department_output_dir(
            Path(output_dir),
            dataset=dataset,
            resolution_m=file.resolution_m or resolution_m,
            department=file.department,
        )
        target = destination / file.file_name
        if dry_run:
            paths.append(target)
            continue
        paths.append(
            download_file(
                file,
                destination,
                session=session,
                timeout=timeout,
                rate_limiter=limiter,
                overwrite=overwrite,
            )
        )
    return paths


def fetch_ign_dem(
    *,
    output_dir: str | Path,
    bbox: tuple[float, float, float, float],
    departments: Sequence[str] | None = None,
    dataset: IgnDemDataset = "bd-alti",
    resolution_m: float | None = None,
    file_format: str = "ASC",
    crs: str | None = None,
    force_refresh: bool = False,
    timeout: float = 120.0,
    requests_per_second: float = 8.0,
    session: requests.Session | None = None,
) -> Path:
    """Build one GeoTIFF of an IGN DEM product over ``bbox`` (EPSG:2154).

    ``bd-alti`` (25 m, ASC) downloads, extracts and merges the department
    archives. ``rge-alti`` (1 m or 5 m, 5 m by default; inland, 5 m is the 1 m
    centre pixel unchanged) is assembled from WMS-Raster tiles, see ``fetch_rge_alti``; ``departments``, ``file_format``
    and ``crs`` do not apply to it.
    """

    normalized_dataset = _normalize_dataset(dataset)
    normalized_format = file_format.upper()
    if normalized_dataset == "rge-alti":
        return fetch_rge_alti(
            output_dir=output_dir,
            bbox=bbox,
            resolution_m=resolution_m,
            force_refresh=force_refresh,
            timeout=timeout,
            requests_per_second=requests_per_second,
            session=session,
        )
    resolved_resolution = 25.0 if resolution_m is None else resolution_m
    if float(resolved_resolution) != 25.0 or normalized_format != "ASC":
        raise NotImplementedError(
            "BD ALTI assembly through ign_geoplateforme_dem supports only "
            "resolution_m=25 and file_format='ASC'."
        )

    from hydromodpy.data.variables.dem.apis._bdalti_archive_index import (
        _extract_7z,
        _find_asc_files,
        _request_hash_str,
    )
    from hydromodpy.spatial.administrative.france import (
        department_code_to_padded,
        find_departments_in_bbox,
    )

    output_root = Path(output_dir)
    processed_dir = output_root / "processed"
    raw_dir = output_root / "raw_ign"
    extracted_dir = output_root / "extracted_ign"
    processed_dir.mkdir(parents=True, exist_ok=True)

    if departments:
        dept_codes = sorted({department_code_to_padded(dept) for dept in departments})
    else:
        dept_codes = find_departments_in_bbox(bbox)
    if not dept_codes:
        raise ValueError(
            f"No department found overlapping bbox {bbox}. "
            "Ensure the bbox is in EPSG:2154 (Lambert-93)."
        )

    bbox_hash = _request_hash_str(bbox, dept_codes=dept_codes)
    merged_tif = processed_dir / f"dem_ign_geoplateforme_bdalti_25m_{bbox_hash}.tif"
    cache_request = _processed_cache_request(
        bbox=bbox,
        departments=dept_codes,
        dataset="bd-alti",
        resolution_m=25.0,
        file_format="ASC",
        crs=crs,
    )
    metadata_path = _processed_metadata_path(merged_tif)
    if not force_refresh and _processed_cache_is_usable(
        merged_tif,
        metadata_path=metadata_path,
        request=cache_request,
    ):
        return merged_tif

    archive_paths = download_ign_dem_departments(
        output_dir=raw_dir,
        departments=dept_codes,
        dataset="bd-alti",
        resolution_m=25.0,
        file_format="ASC",
        crs=crs,
        dry_run=False,
        max_files=None,
        timeout=timeout,
        requests_per_second=requests_per_second,
        overwrite=force_refresh,
        session=session,
    )
    if not archive_paths:
        raise ValueError(f"No IGN DEM archive found for departments: {dept_codes}")

    import shutil
    import tempfile

    asc_files: list[Path] = []
    extracted_dir.mkdir(parents=True, exist_ok=True)
    for archive_path in progress.track(archive_paths, "Extracting IGN DEM archives"):
        archive_path = Path(archive_path)
        archive_extract_dir = _archive_extract_dir(extracted_dir, archive_path)
        marker = archive_extract_dir / ".extracted"
        # One extractor per archive: another process would delete this tree
        # while this one moves its own copy in.
        with FileLock(f"{archive_extract_dir}.lock"):
            if force_refresh and archive_extract_dir.exists():
                shutil.rmtree(archive_extract_dir)
            if not marker.exists():
                with tempfile.TemporaryDirectory(
                    prefix=f"ign_dem_{archive_extract_dir.name}_", dir=extracted_dir
                ) as tmp:
                    tmp_dir = Path(tmp)
                    _extract_7z(archive_path, tmp_dir)
                    _install_extracted_archive(
                        tmp_dir=tmp_dir,
                        archive_path=archive_path,
                        archive_extract_dir=archive_extract_dir,
                    )
                marker.touch()
            asc_files.extend(_find_asc_files(archive_extract_dir))

    if not asc_files:
        raise ValueError(f"No ASC files found for departments: {dept_codes}")

    import rasterio
    from rasterio.merge import merge

    with progress.status("Merging DEM tiles"):
        datasets = []
        try:
            for asc_path in asc_files:
                datasets.append(rasterio.open(str(asc_path)))
            mosaic, mosaic_transform = merge(datasets, bounds=bbox)
        finally:
            for dataset_handle in datasets:
                dataset_handle.close()
        mosaic = _mask_sea(_normalize_dem_nodata(mosaic))

        profile = {
            "driver": "GTiff",
            "height": mosaic.shape[1],
            "width": mosaic.shape[2],
            "count": mosaic.shape[0],
            "transform": mosaic_transform,
            "crs": "EPSG:2154",
            "dtype": mosaic.dtype,
            "compress": "deflate",
            "nodata": -9999,
        }
        with (
            staged_path(merged_tif) as staged,
            rasterio.open(str(staged), "w", **profile) as dst,
        ):
            dst.write(mosaic)
    _write_processed_cache_metadata(
        metadata_path,
        request=cache_request,
        raster_path=merged_tif,
        archive_paths=archive_paths,
    )
    return merged_tif


def fetch_rge_alti(
    *,
    output_dir: str | Path,
    bbox: tuple[float, float, float, float],
    resolution_m: float | None = None,
    max_pixels: int = RGE_ALTI_MAX_PIXELS,
    tile_px: int = wms.DEFAULT_TILE_PX,
    force_refresh: bool = False,
    timeout: float = 120.0,
    requests_per_second: float = 8.0,
    session: requests.Session | None = None,
) -> Path:
    """Assemble the RGE ALTI over ``bbox`` from Geoplateforme WMS-Raster tiles.

    The box grows outward to multiples of the resolution so that the pixels sit
    on the native grid. Water and the cells the product does not cover are nodata
    (-9999), see ``mask_rge_alti``. Asking the service for a size other than 1 m
    or 5 m is an error: the server resamples it with an undocumented kernel, see
    ``RGE_ALTI_RESOLUTIONS_M``.

    The layer answers outside France as well, with another, coarser source and
    no nodata. A box that touches no department is refused. A box that overlaps a
    border is built, and the sidecar counts the valid pixels outside the
    department outlines buffered by 1 km (a warning above 1 %): they are not
    masked.

    A request above ``max_pixels`` raises ``ValueError`` before any download.
    The tiles go to a raw raster as they arrive, so memory holds one tile; a
    second pass masks it by strips of rows, with a halo so that the rule sees
    across tile edges. The result is cached by box, dataset, resolution and
    processing version.
    """

    from hydromodpy.data.variables.dem.apis._bdalti_archive_index import _request_hash_str
    from hydromodpy.spatial.administrative.france import find_departments_in_bbox

    resolution = RGE_ALTI_DEFAULT_RESOLUTION_M if resolution_m is None else float(resolution_m)
    if resolution not in RGE_ALTI_RESOLUTIONS_M:
        allowed = ", ".join(f"{value:g}" for value in RGE_ALTI_RESOLUTIONS_M)
        raise ValueError(
            f"RGE ALTI is served at {allowed} m only, got resolution_m={resolution:g}."
        )
    snapped = wms.snap_bbox(bbox, resolution)
    rows, cols = wms.grid_shape(snapped, resolution)
    if rows <= 0 or cols <= 0:
        raise ValueError(f"Empty RGE ALTI request: bbox {tuple(bbox)}.")
    if rows * cols > max_pixels:
        advice = "Reduce the extent"
        if resolution == 1.0:
            advice += " or use resolution_m = 5"
        raise ValueError(
            f"RGE ALTI request of {cols} x {rows} pixels ({rows * cols / 1e6:.0f} million, "
            f"{rows * cols * 4 / 1e9:.1f} GB as float32) at {resolution:g} m over "
            f"{(snapped[2] - snapped[0]) / 1000:.1f} x {(snapped[3] - snapped[1]) / 1000:.1f} km "
            f"is above the limit of {max_pixels / 1e6:.0f} million pixels. {advice}."
        )
    if not find_departments_in_bbox(bbox):
        raise ValueError(
            f"No department found overlapping bbox {tuple(bbox)}. "
            "Ensure the bbox is in EPSG:2154 (Lambert-93)."
        )

    processed_dir = Path(output_dir) / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    merged_tif = (
        processed_dir
        / f"dem_ign_geoplateforme_rgealti_{_resolution_label(resolution)}_{_request_hash_str(bbox)}.tif"
    )
    cache_request = _processed_cache_request(
        bbox=bbox,
        departments=[],
        dataset="rge-alti",
        resolution_m=resolution,
        file_format="GEOTIFF",
        crs=None,
        processing_version=RGE_ALTI_PROCESSING_VERSION,
    )
    metadata_path = _processed_metadata_path(merged_tif)
    if not force_refresh and _processed_cache_is_usable(
        merged_tif, metadata_path=metadata_path, request=cache_request
    ):
        return merged_tif

    import tempfile

    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.windows import Window

    tiles = list(wms.plan_tiles(snapped, resolution, tile_px=tile_px))
    limiter = RateLimiter(requests_per_second=requests_per_second)
    profile = {
        "driver": "GTiff",
        "height": rows,
        "width": cols,
        "count": 1,
        "transform": from_origin(snapped[0], snapped[3], resolution, resolution),
        "crs": "EPSG:2154",
        "dtype": "float32",
        "nodata": -9999,
        "compress": "deflate",
        "predictor": 3,
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }
    with tempfile.TemporaryDirectory(prefix=".rge_raw_", dir=processed_dir) as scratch:
        raw_path = Path(scratch) / "raw.tif"
        with rasterio.open(str(raw_path), "w", **profile) as raw:
            for tile in progress.track(tiles, "Fetching RGE ALTI tiles"):
                data = wms.fetch_tile(
                    RGE_ALTI_WMS_LAYER,
                    tile,
                    session=session,
                    timeout=timeout,
                    rate_limiter=limiter,
                )
                raw.write(
                    np.where(np.isfinite(data), data, -9999.0).astype("float32"),
                    1,
                    window=Window(tile.col_off, tile.row_off, tile.width, tile.height),
                )
        departments = find_departments_in_bbox(
            (
                snapped[0] - RGE_ALTI_BORDER_BUFFER_M,
                snapped[1] - RGE_ALTI_BORDER_BUFFER_M,
                snapped[2] + RGE_ALTI_BORDER_BUFFER_M,
                snapped[3] + RGE_ALTI_BORDER_BUFFER_M,
            )
        )
        with (
            staged_path(merged_tif) as staged,
            rasterio.open(str(raw_path)) as raw,
            rasterio.open(str(staged), "w", **profile) as dst,
        ):
            valid_pixels, foreign_pixels = _mask_raster_by_strips(
                raw, dst, snapped=snapped, resolution=resolution, departments=departments
            )
            if valid_pixels == 0:
                raise ValueError(
                    f"RGE ALTI holds no elevation over bbox {tuple(bbox)} (sea or no coverage)."
                )
    foreign_share = foreign_pixels / valid_pixels
    if foreign_share > RGE_ALTI_FOREIGN_WARN_SHARE:
        logger.warning(
            "RGE ALTI box %s: %.1f %% of the valid pixels lie outside the French department "
            "outlines (buffered by %.0f m), where the layer serves another source. "
            "They are kept as the server answered.",
            tuple(bbox),
            100.0 * foreign_share,
            RGE_ALTI_BORDER_BUFFER_M,
        )
    _write_processed_cache_metadata(
        metadata_path,
        request=cache_request,
        raster_path=merged_tif,
        archive_paths=[],
        wms_source={
            "layer": RGE_ALTI_WMS_LAYER,
            "url": wms.WMS_URL,
            "tiles": len(tiles),
            "tile_px": tile_px,
            "snapped_bbox": list(snapped),
            "valid_pixels": valid_pixels,
            "outside_france_pixels": foreign_pixels,
            "outside_france_share": foreign_share,
            "outside_france_buffer_m": RGE_ALTI_BORDER_BUFFER_M,
        },
    )
    return merged_tif


def mask_rge_alti(data):
    """Return ``data`` with the RGE ALTI water, nodata and blend set to NaN.

    ``data`` holds the server nodata as NaN. Masked are:

    - the nodata itself;
    - the flat water plateau, ``abs(v + 5) < 0.005``;
    - the values below -5.01 m within ``RGE_ALTI_BLEND_REACH_PX`` pixels of
      either: the server blends its -99999 into the neighbouring land there;
    - the land pixels 8-adjacent to that blend band, whose weight of nodata is
      too small to push them below -5.01 m but still biases them low.

    Land below -5 m far from water and nodata (a quarry floor) is kept. The rule
    looks ``RGE_ALTI_BLEND_REACH_PX + 1`` pixels around a pixel; a caller that
    cuts the raster must keep that halo.
    """

    import numpy as np
    from scipy import ndimage

    values = np.asarray(data, dtype="float32")
    with np.errstate(invalid="ignore"):
        seed = np.isnan(values) | (np.abs(values - RGE_ALTI_WATER_M) < 0.005)
        near = ndimage.binary_dilation(
            seed, structure=np.ones((3, 3), dtype=bool), iterations=RGE_ALTI_BLEND_REACH_PX
        )
        blend = near & (values < RGE_ALTI_WATER_M - 0.01)
    rim = ndimage.binary_dilation(blend, structure=np.ones((3, 3), dtype=bool))
    masked = values.copy()
    masked[seed | blend | rim] = np.nan
    return masked


def _mask_raster_by_strips(
    raw,
    dst,
    *,
    snapped: tuple[float, float, float, float],
    resolution: float,
    departments: Sequence[str],
) -> tuple[int, int]:
    """Mask ``raw`` into ``dst`` strip by strip; return valid and foreign pixel counts.

    Each strip is read with a halo of ``_MASK_HALO_PX`` rows, so the rule of
    ``mask_rge_alti`` sees across the strip seams as it does across tile edges.
    A pixel is foreign when it is valid and outside the department outlines
    buffered by ``RGE_ALTI_BORDER_BUFFER_M``.
    """

    import numpy as np
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    from rasterio.windows import Window
    from shapely.geometry import box

    from hydromodpy.spatial.administrative.france import geometry_for_departments

    rows, cols = raw.height, raw.width
    outline = None
    if departments:
        outline = geometry_for_departments(departments).buffer(RGE_ALTI_BORDER_BUFFER_M)
        outline = outline.intersection(box(*snapped))
        if outline.is_empty:
            outline = None
    valid_pixels = 0
    foreign_pixels = 0
    for row0 in range(0, rows, _STRIP_ROWS):
        row1 = min(rows, row0 + _STRIP_ROWS)
        first = max(0, row0 - _MASK_HALO_PX)
        last = min(rows, row1 + _MASK_HALO_PX)
        block = raw.read(1, window=Window(0, first, cols, last - first))
        block[block <= -9990.0] = np.nan
        core = mask_rge_alti(block)[row0 - first : row1 - first]
        valid = np.isfinite(core)
        dst.write(
            np.where(valid, core, -9999.0).astype("float32"),
            1,
            window=Window(0, row0, cols, row1 - row0),
        )
        valid_pixels += int(valid.sum())
        if outline is None:
            foreign_pixels += int(valid.sum())
            continue
        inside = rasterize(
            [(outline, 1)],
            out_shape=core.shape,
            transform=from_origin(
                snapped[0], snapped[3] - row0 * resolution, resolution, resolution
            ),
            fill=0,
            dtype="uint8",
        ).astype(bool)
        foreign_pixels += int((valid & ~inside).sum())
    return valid_pixels, foreign_pixels


def _discover_department_files(
    *,
    resource_name: str,
    department: str,
    dataset: str,
    resolution_m: float | None,
    file_format: str,
    filters: DiscoveryFilters,
    session: requests.Session | None,
    timeout: float,
    rate_limiter: RateLimiter | None,
) -> list[DownloadFile]:
    discovered: list[DownloadFile] = []
    subresources = list_subresources(
        resource_name,
        filters,
        session=session,
        timeout=timeout,
        rate_limiter=rate_limiter,
    )
    for subresource in subresources:
        subresource_name = _entry_name(subresource)
        for file in list_files(
            resource_name,
            subresource_name,
            filters,
            session=session,
            timeout=timeout,
            rate_limiter=rate_limiter,
        ):
            enriched = replace(
                file,
                department=department,
                dataset=dataset,
                resolution_m=resolution_m,
            )
            if _file_matches(
                enriched.file_name, resolution_m=resolution_m, file_format=file_format
            ):
                discovered.append(enriched)
    return discovered


def _bdalti_archive_index_fallback_files(
    *,
    department: str,
    resolution_m: float | None,
    file_format: str,
) -> list[DownloadFile]:
    """Return BD ALTI files from the internal archive index.

    This is an internal resilience path for the Geoplateforme client, not a
    separate legacy user-facing source.
    """
    if resolution_m is not None and float(resolution_m) != 25.0:
        return []
    if file_format.upper() != "ASC":
        return []
    from hydromodpy.data.variables.dem.apis._bdalti_archive_index import (
        BDALTI_25M_ASC_ARCHIVES,
    )

    padded = department[1:] if department.startswith("D") else department
    archive_name = BDALTI_25M_ASC_ARCHIVES.get(padded)
    if archive_name is None:
        return []
    file_name = f"{archive_name}.7z"
    return [
        DownloadFile(
            resource_name="BDALTI",
            subresource_name=archive_name,
            file_name=file_name,
            url=build_download_url("BDALTI", archive_name, file_name),
            department=department,
            dataset="bd-alti",
            resolution_m=25.0,
        )
    ]


def _resource_name(dataset: str) -> str:
    try:
        return DATASET_RESOURCE_NAMES[dataset]
    except KeyError as exc:
        allowed = ", ".join(sorted(DATASET_RESOURCE_NAMES))
        raise ValueError(
            f"Unsupported DEM dataset {dataset!r}. Expected one of: {allowed}"
        ) from exc


def _normalize_dataset(dataset: str) -> IgnDemDataset:
    normalized = str(dataset).strip().lower()
    _resource_name(normalized)
    return normalized  # type: ignore[return-value]


def _entry_name(entry: object) -> str:
    identifier = str(getattr(entry, "identifier", "") or "").strip()
    title = str(getattr(entry, "title", "") or "").strip()
    if identifier:
        return Path(identifier.rstrip("/")).name
    return title


def _file_matches(
    file_name: str,
    *,
    resolution_m: float | None,
    file_format: str,
) -> bool:
    upper = file_name.upper()
    if file_format and file_format.upper() not in upper:
        return False
    if resolution_m is None:
        return True
    return _resolution_token(resolution_m) in upper


def _resolution_token(resolution_m: float) -> str:
    value = float(resolution_m)
    if value.is_integer():
        return f"{int(value)}M"
    return f"{str(value).replace('.', '_')}M"


def _resolution_label(resolution_m: float | None) -> str:
    if resolution_m is None:
        return "unknown_resolution"
    value = float(resolution_m)
    if value.is_integer():
        return f"{int(value)}m"
    return f"{str(value).replace('.', '_')}m"


def _department_output_dir(
    output_dir: Path,
    *,
    dataset: str,
    resolution_m: float | None,
    department: str | None,
) -> Path:
    department_dir = department or "unknown_department"
    return output_dir / dataset / _resolution_label(resolution_m) / department_dir


def _archive_extract_dir(extracted_dir: Path, archive_path: Path) -> Path:
    """Return a short stable extraction directory for Windows path limits."""

    department = archive_path.parent.name
    if not department.upper().startswith("D"):
        department = "DUNK"
    digest = hashlib.sha1(archive_path.stem.encode("utf-8")).hexdigest()[:8]
    return extracted_dir / f"{department}_{digest}"


def _install_extracted_archive(
    *,
    tmp_dir: Path,
    archive_path: Path,
    archive_extract_dir: Path,
) -> None:
    """Move an extracted archive into the stable cache directory."""

    import os
    import shutil

    asc_files = sorted(tmp_dir.rglob("*.asc"))
    archive_root = tmp_dir / archive_path.stem
    if archive_extract_dir.exists():
        shutil.rmtree(archive_extract_dir)
    archive_extract_dir.parent.mkdir(parents=True, exist_ok=True)
    if asc_files:
        common_asc_dir = Path(os.path.commonpath([str(path.parent) for path in asc_files]))
        shutil.move(str(common_asc_dir), str(archive_extract_dir))
        return
    if archive_root.exists():
        shutil.move(str(archive_root), str(archive_extract_dir))
        return
    archive_extract_dir.mkdir(parents=True, exist_ok=True)
    for child in tmp_dir.iterdir():
        shutil.move(str(child), str(archive_extract_dir / child.name))


def _normalize_dem_nodata(mosaic):
    """Normalize IGN sentinel values before writing a GeoTIFF."""

    import numpy as np

    data = np.asarray(mosaic)
    if not np.issubdtype(data.dtype, np.floating):
        data = data.astype("float32")
    data[data <= -9990.0] = -9999.0
    return data


def _mask_sea(mosaic):
    """Set the BD ALTI sea to nodata.

    BD ALTI writes the sea as 0 m, not as nodata. A zero-valued region that
    touches the raster edge or a nodata cell is sea; an inland one is kept.
    Left in place, the sea is one flat plateau that the breach step cannot
    route in reasonable time.
    """

    import numpy as np
    from scipy import ndimage

    data = np.asarray(mosaic)
    for band in data:
        zero = band == 0.0
        if not zero.any():
            continue
        seed = ndimage.binary_dilation(band == -9999.0)
        seed[0, :] = seed[-1, :] = seed[:, 0] = seed[:, -1] = True
        labels, _ = ndimage.label(zero)
        sea_labels = np.unique(labels[seed & zero])
        band[np.isin(labels, sea_labels[sea_labels > 0])] = -9999.0
    return data


def _processed_metadata_path(raster_path: Path) -> Path:
    return raster_path.with_suffix(".json")


def _processed_cache_request(
    *,
    bbox: tuple[float, float, float, float],
    departments: Sequence[str],
    dataset: str,
    resolution_m: float,
    file_format: str,
    crs: str | None,
    processing_version: str | None = None,
) -> dict[str, object]:
    request: dict[str, object] = {
        "schema_version": "ign_geoplateforme_dem_processed_v2",
        "dataset": dataset,
        "resolution_m": float(resolution_m),
        "file_format": file_format.upper(),
        "crs": crs or "EPSG:2154",
        "bbox": [float(value) for value in bbox],
        "departments": list(departments),
    }
    if processing_version is not None:
        # Only a product whose masking rule changes carries one: the BD ALTI
        # requests, and the rasters cached for them, stay as they were.
        request["processing_version"] = processing_version
    return request


def _processed_cache_is_usable(
    raster_path: Path,
    *,
    metadata_path: Path,
    request: dict[str, object],
) -> bool:
    if not raster_path.is_file():
        return False
    if metadata_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if metadata.get("request") != request:
            return False
        return _processed_raster_matches_request(raster_path, request)

    if not _processed_raster_matches_request(raster_path, request):
        return False
    _write_processed_cache_metadata(
        metadata_path,
        request=request,
        raster_path=raster_path,
        archive_paths=[],
        adopted_unversioned_cache=True,
    )
    return True


def _processed_raster_matches_request(raster_path: Path, request: Mapping[str, object]) -> bool:
    try:
        import rasterio

        with rasterio.open(str(raster_path)) as dataset:
            if dataset.width <= 0 or dataset.height <= 0:
                return False
            if str(dataset.crs or "") != "EPSG:2154":
                return False
            if dataset.nodata != -9999:
                return False
            resolution = float(request.get("resolution_m") or 0.0)
            if resolution and (
                abs(abs(float(dataset.res[0])) - resolution) > 1.0e-6
                or abs(abs(float(dataset.res[1])) - resolution) > 1.0e-6
            ):
                return False
            raw_bbox = request.get("bbox")
            if isinstance(raw_bbox, list) and len(raw_bbox) == 4:
                bbox = tuple(float(value) for value in raw_bbox)
                bounds = dataset.bounds
                tolerance = max(abs(float(dataset.res[0])), abs(float(dataset.res[1])), 1.0)
                if (
                    bounds.left > bbox[0] + tolerance
                    or bounds.bottom > bbox[1] + tolerance
                    or bounds.right < bbox[2] - tolerance
                    or bounds.top < bbox[3] - tolerance
                ):
                    return False
    except Exception:
        return False
    return True


def _write_processed_cache_metadata(
    metadata_path: Path,
    *,
    request: dict[str, object],
    raster_path: Path,
    archive_paths: Sequence[Path],
    adopted_unversioned_cache: bool = False,
    wms_source: Mapping[str, object] | None = None,
) -> None:
    metadata = {
        "request": request,
        "raster": {
            "path": raster_path.name,
            "size_bytes": raster_path.stat().st_size if raster_path.exists() else None,
        },
        "archives": [
            {
                "path": str(path),
                "size_bytes": path.stat().st_size if path.exists() else None,
            }
            for path in archive_paths
        ],
        "adopted_unversioned_cache": adopted_unversioned_cache,
        "created_at_utc": datetime.now(UTC).isoformat(),
    }
    if wms_source is not None:
        metadata["wms"] = dict(wms_source)
    with staged_path(metadata_path) as staged:
        staged.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
            encoding="utf-8",
        )


__all__ = [
    "DATASET_RESOURCE_NAMES",
    "discover_ign_dem_files",
    "download_ign_dem_departments",
    "fetch_ign_dem",
    "fetch_rge_alti",
    "normalize_department_code",
]
