"""French IGN DEM archive discovery through Geoplateforme."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import requests

from hydromodpy.data.common.administrative.france import department_code_to_padded
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

IgnDemDataset = Literal["bd-alti", "rge-alti"]

DATASET_RESOURCE_NAMES: dict[str, str] = {
    "bd-alti": "BDALTI",
    "rge-alti": "RGEALTI",
}


def normalize_department_code(value: str) -> str:
    """Normalize a French department code to the Geoplateforme ``Dxxx`` form."""

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
    for file in files:
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
    """Download, extract, merge, and crop an IGN DEM product.

    The production assembly path currently supports BD ALTI 25 m ASC. RGE ALTI
    discovery/download is available through ``download_ign_dem_departments`` but
    its raster assembly is intentionally left explicit until fragmented archives
    and large 1 m/5 m requests are handled safely.
    """

    normalized_dataset = _normalize_dataset(dataset)
    normalized_format = file_format.upper()
    resolved_resolution = 25.0 if resolution_m is None and normalized_dataset == "bd-alti" else resolution_m
    if normalized_dataset == "rge-alti":
        raise NotImplementedError(
            "RGE ALTI raster assembly is not implemented in fetch_ign_dem yet. "
            "Use download_ign_dem_departments(..., dataset='rge-alti', dry_run=True) "
            "to inspect raw archives, or request BD ALTI 25 m ASC for assembled GeoTIFFs."
        )
    if normalized_dataset != "bd-alti" or float(resolved_resolution or 0.0) != 25.0 or normalized_format != "ASC":
        raise NotImplementedError(
            "DEM raster assembly through ign_geoplateforme_dem currently supports "
            "only dataset='bd-alti', resolution_m=25, file_format='ASC'. "
            "Use the CLI/download helper for raw RGE ALTI archives."
        )

    from hydromodpy.data.common.administrative.france import (
        department_code_to_padded,
        find_departments_in_bbox,
    )
    from hydromodpy.data.variables.dem.apis._bdalti_archive_index import (
        _extract_7z,
        _find_asc_files,
        _request_hash_str,
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

    asc_files: list[Path] = []
    for archive_path in archive_paths:
        archive_path = Path(archive_path)
        archive_extract_dir = _archive_extract_dir(extracted_dir, archive_path)
        marker = archive_extract_dir / ".extracted"
        if force_refresh and archive_extract_dir.exists():
            import shutil

            shutil.rmtree(archive_extract_dir)
        if not marker.exists():
            import shutil
            import tempfile

            with tempfile.TemporaryDirectory(prefix=f"ign_dem_{archive_extract_dir.name}_") as tmp:
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

    datasets = []
    try:
        for asc_path in asc_files:
            datasets.append(rasterio.open(str(asc_path)))
        mosaic, mosaic_transform = merge(datasets, bounds=bbox)
    finally:
        for dataset_handle in datasets:
            dataset_handle.close()
    mosaic = _normalize_dem_nodata(mosaic)

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
    with rasterio.open(str(merged_tif), "w", **profile) as dst:
        dst.write(mosaic)
    _write_processed_cache_metadata(
        metadata_path,
        request=cache_request,
        raster_path=merged_tif,
        archive_paths=archive_paths,
    )
    return merged_tif


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
            if _file_matches(enriched.file_name, resolution_m=resolution_m, file_format=file_format):
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
        raise ValueError(f"Unsupported DEM dataset {dataset!r}. Expected one of: {allowed}") from exc


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
) -> dict[str, object]:
    return {
        "schema_version": "ign_geoplateforme_dem_processed_v1",
        "dataset": dataset,
        "resolution_m": float(resolution_m),
        "file_format": file_format.upper(),
        "crs": crs or "EPSG:2154",
        "bbox": [float(value) for value in bbox],
        "departments": list(departments),
    }


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
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "DATASET_RESOURCE_NAMES",
    "discover_ign_dem_files",
    "download_ign_dem_departments",
    "fetch_ign_dem",
    "normalize_department_code",
]
