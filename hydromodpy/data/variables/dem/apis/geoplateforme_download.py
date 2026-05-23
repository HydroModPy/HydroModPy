"""Geoplateforme download API helpers for DEM archives.

This module is intentionally provider-level plumbing. It discovers Atom
entries, converts download entries to local file descriptors, and downloads
files with conservative retry/rate-limit behavior. Product-specific DEM logic
belongs in ``ign_dem_fr.py``.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import requests

CAPABILITIES_URL = "https://data.geopf.fr/telechargement/capabilities"
RESOURCE_URL = "https://data.geopf.fr/telechargement/resource"
DOWNLOAD_URL = "https://data.geopf.fr/telechargement/download"
DEFAULT_USER_AGENT = "hydromodpy/1.0"
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


class GeoPlateformeDownloadError(RuntimeError):
    """Raised when Geoplateforme discovery or download fails."""


@dataclass(frozen=True)
class AtomEntry:
    """Small normalized representation of one Atom entry."""

    title: str
    identifier: str
    links: tuple[str, ...] = ()
    properties: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoveryFilters:
    """Filters forwarded to Geoplateforme discovery endpoints."""

    zone: str | None = None
    file_format: str | None = None
    crs: str | None = None
    polygon: str | None = None
    limit: int = 50
    extra: dict[str, str | int | float | None] = field(default_factory=dict)

    def params(self) -> dict[str, str | int | float]:
        params: dict[str, str | int | float | None] = {
            "zone": self.zone,
            "format": self.file_format,
            "crs": self.crs,
            "polygon": self.polygon,
            "limit": self.limit,
            **self.extra,
        }
        return {key: value for key, value in params.items() if value not in (None, "")}


@dataclass(frozen=True)
class DownloadFile:
    """One downloadable archive or sidecar exposed by Geoplateforme."""

    resource_name: str
    subresource_name: str
    file_name: str
    url: str
    size: int | None = None
    checksum: str | None = None
    department: str | None = None
    dataset: str | None = None
    resolution_m: float | None = None


class RateLimiter:
    """Simple process-local rate limiter."""

    def __init__(self, requests_per_second: float = 8.0):
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive.")
        self._min_interval = 1.0 / float(requests_per_second)
        self._last_request = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delay = self._min_interval - (now - self._last_request)
        if delay > 0:
            time.sleep(delay)
        self._last_request = time.monotonic()


def fetch_atom_entries(
    url: str,
    params: dict[str, str | int | float | None] | None = None,
    *,
    session: requests.Session | None = None,
    timeout: float = 30.0,
    rate_limiter: RateLimiter | None = None,
    max_pages: int | None = None,
    max_entries: int | None = None,
) -> list[AtomEntry]:
    """Fetch all Atom entries from a paginated Geoplateforme endpoint."""

    http = session or _default_session()
    clean_params = {key: value for key, value in (params or {}).items() if value not in (None, "")}
    page = int(clean_params.pop("page", 1) or 1)
    limit = int(clean_params.get("limit", 50) or 50)
    clean_params["limit"] = limit

    entries: list[AtomEntry] = []
    pages_read = 0
    total_entries: int | None = None
    while True:
        request_params = {**clean_params, "page": page}
        response = _request_with_retries(
            http,
            url,
            params=request_params,
            timeout=timeout,
            rate_limiter=rate_limiter,
        )
        page_entries, page_total = _parse_atom_feed(response.text)
        if page_total is not None:
            total_entries = page_total
        if not page_entries:
            break
        entries.extend(page_entries)
        if max_entries is not None and len(entries) >= max_entries:
            return entries[:max_entries]
        pages_read += 1
        if max_pages is not None and pages_read >= max_pages:
            break
        if total_entries is not None and len(entries) >= total_entries:
            break
        page += 1
    return entries


def parse_atom_entries(xml_text: str) -> list[AtomEntry]:
    """Parse Atom entries from an XML text payload."""

    entries, _ = _parse_atom_feed(xml_text)
    return entries


def find_resources(
    dataset: str,
    filters: DiscoveryFilters | None = None,
    *,
    session: requests.Session | None = None,
    timeout: float = 30.0,
    rate_limiter: RateLimiter | None = None,
) -> list[AtomEntry]:
    """Find resource entries matching a dataset token such as ``BDALTI``."""

    token = _normalized_token(dataset)
    entries = fetch_atom_entries(
        CAPABILITIES_URL,
        (filters or DiscoveryFilters()).params(),
        session=session,
        timeout=timeout,
        rate_limiter=rate_limiter,
    )
    return [
        entry
        for entry in entries
        if token in _normalized_token(" ".join([entry.title, entry.identifier, *entry.links]))
    ]


def list_subresources(
    resource_name: str,
    filters: DiscoveryFilters | None = None,
    *,
    session: requests.Session | None = None,
    timeout: float = 30.0,
    rate_limiter: RateLimiter | None = None,
) -> list[AtomEntry]:
    """List subresources for one Geoplateforme resource."""

    return fetch_atom_entries(
        f"{RESOURCE_URL}/{quote(resource_name.strip())}",
        (filters or DiscoveryFilters()).params(),
        session=session,
        timeout=timeout,
        rate_limiter=rate_limiter,
    )


def list_files(
    resource_name: str,
    subresource_name: str,
    filters: DiscoveryFilters | None = None,
    *,
    session: requests.Session | None = None,
    timeout: float = 30.0,
    rate_limiter: RateLimiter | None = None,
) -> list[DownloadFile]:
    """List downloadable files for one resource/subresource pair."""

    entries = fetch_atom_entries(
        f"{RESOURCE_URL}/{quote(resource_name.strip())}/{quote(subresource_name.strip())}",
        (filters or DiscoveryFilters()).params(),
        session=session,
        timeout=timeout,
        rate_limiter=rate_limiter,
    )
    return [
        _download_file_from_atom_entry(
            entry,
            resource_name=resource_name,
            subresource_name=subresource_name,
        )
        for entry in entries
    ]


def download_file(
    file: DownloadFile,
    destination: str | Path,
    *,
    session: requests.Session | None = None,
    timeout: float = 120.0,
    rate_limiter: RateLimiter | None = None,
    overwrite: bool = False,
    chunk_size: int = 1024 * 1024,
) -> Path:
    """Download one file, skipping non-empty files already available locally."""

    target = _target_path(destination, file.file_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0 and not overwrite:
        return target

    partial = target.with_name(f"{target.name}.part")
    existing_size = partial.stat().st_size if partial.exists() and not overwrite else 0
    headers = {"Range": f"bytes={existing_size}-"} if existing_size else None
    http = session or _default_session()
    response = _request_with_retries(
        http,
        file.url,
        timeout=timeout,
        rate_limiter=rate_limiter,
        stream=True,
        headers=headers,
    )
    mode = "ab" if existing_size and getattr(response, "status_code", 200) == 206 else "wb"
    with partial.open(mode) as handle:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                handle.write(chunk)
    partial.replace(target)
    return target


def build_download_url(resource_name: str, subresource_name: str, file_name: str) -> str:
    """Build a canonical Geoplateforme download URL."""

    return (
        f"{DOWNLOAD_URL}/{quote(resource_name.strip())}/"
        f"{quote(subresource_name.strip())}/{quote(file_name.strip())}"
    )


def _default_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
    return session


def _request_with_retries(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float,
    rate_limiter: RateLimiter | None,
    stream: bool = False,
    headers: dict[str, str] | None = None,
    attempts: int = 3,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        if rate_limiter is not None:
            rate_limiter.wait()
        try:
            response = session.get(
                url,
                params=params,
                timeout=timeout,
                stream=stream,
                headers=headers,
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(min(2.0**attempt, 8.0))
            continue
        status_code = int(getattr(response, "status_code", 0))
        if status_code in TRANSIENT_STATUS_CODES and attempt < attempts:
            time.sleep(min(2.0**attempt, 8.0))
            continue
        if status_code >= 400:
            raise GeoPlateformeDownloadError(
                f"Geoplateforme request failed ({status_code}) for {url}"
            )
        return response
    raise GeoPlateformeDownloadError(f"Geoplateforme request failed for {url}") from last_error


def _parse_atom_feed(xml_text: str) -> tuple[list[AtomEntry], int | None]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise GeoPlateformeDownloadError("Geoplateforme response is not valid Atom XML.") from exc

    total_entries: int | None = None
    entries: list[AtomEntry] = []
    for element in root.iter():
        local = _local_name(element.tag)
        if local.lower() == "totalentries" and element.text:
            try:
                total_entries = int(element.text.strip())
            except ValueError:
                total_entries = None
        if local == "entry":
            entries.append(_parse_atom_entry(element))
    return entries, total_entries


def _parse_atom_entry(element: ET.Element) -> AtomEntry:
    title = ""
    identifier = ""
    links: list[str] = []
    properties: dict[str, str] = {}
    for child in element:
        local = _local_name(child.tag)
        text = (child.text or "").strip()
        if local == "title":
            title = text
        elif local == "id":
            identifier = text
        elif local == "link":
            href = child.attrib.get("href")
            if href:
                links.append(href)
        elif text:
            properties[local] = text
    if not identifier:
        identifier = title
    return AtomEntry(title=title, identifier=identifier, links=tuple(links), properties=properties)


def _download_file_from_atom_entry(
    entry: AtomEntry,
    *,
    resource_name: str,
    subresource_name: str,
) -> DownloadFile:
    url = _download_url_from_entry(entry)
    file_name = _file_name_from_entry(entry, url=url)
    return DownloadFile(
        resource_name=resource_name,
        subresource_name=subresource_name,
        file_name=file_name,
        url=url or build_download_url(resource_name, subresource_name, file_name),
        size=_int_property(entry.properties, "size", "taille", "filesize"),
        checksum=_string_property(entry.properties, "checksum", "md5"),
    )


def _download_url_from_entry(entry: AtomEntry) -> str:
    for link in entry.links:
        if "/telechargement/download/" in link:
            return link
    return entry.links[0] if entry.links else ""


def _file_name_from_entry(entry: AtomEntry, *, url: str) -> str:
    for key in ("file", "filename", "fileName", "name"):
        value = entry.properties.get(key)
        if value:
            return Path(value).name
    if url:
        parsed = urlparse(url)
        if parsed.path:
            return unquote(Path(parsed.path).name)
    return Path(entry.title or entry.identifier).name


def _target_path(destination: str | Path, file_name: str) -> Path:
    path = Path(destination)
    if path.exists() and path.is_dir():
        return path / file_name
    if path.suffix:
        return path
    return path / file_name


def _int_property(properties: dict[str, str], *keys: str) -> int | None:
    for key in keys:
        value = properties.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except ValueError:
            continue
    return None


def _string_property(properties: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = properties.get(key)
        if value:
            return value
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _normalized_token(value: str) -> str:
    return "".join(char for char in value.upper() if char.isalnum())


__all__ = [
    "AtomEntry",
    "DiscoveryFilters",
    "DownloadFile",
    "GeoPlateformeDownloadError",
    "RateLimiter",
    "build_download_url",
    "download_file",
    "fetch_atom_entries",
    "find_resources",
    "list_files",
    "list_subresources",
    "parse_atom_entries",
]
