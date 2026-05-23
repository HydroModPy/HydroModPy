"""French IGN DEM archive discovery through Geoplateforme."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
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
    """Discover downloadable IGN DEM archives for departments."""

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
            department_files = _static_bdalti_files(
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


def _static_bdalti_files(
    *,
    department: str,
    resolution_m: float | None,
    file_format: str,
) -> list[DownloadFile]:
    if resolution_m is not None and float(resolution_m) != 25.0:
        return []
    if file_format.upper() != "ASC":
        return []
    from hydromodpy.data.variables.dem.apis.ign_bdalti import _BDALTI_ARCHIVES

    padded = department[1:] if department.startswith("D") else department
    archive_name = _BDALTI_ARCHIVES.get(padded)
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


__all__ = [
    "DATASET_RESOURCE_NAMES",
    "discover_ign_dem_files",
    "download_ign_dem_departments",
    "normalize_department_code",
]
