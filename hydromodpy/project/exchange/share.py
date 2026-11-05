"""Share a run with its data: the install index of a run, and its installation elsewhere.

Why here
--------
A run names its inputs in ``inputs.json`` and ``manifest.json`` (``results``);
the bytes, their sidecars, their station rows and the rows of the data cache
that serve them belong to the workspace (``data``). ``catalog`` is the layer
that sees both, so the index of a run is built here and handed to
:func:`hydromodpy.results.export.publish.publish`, which never reads ``data``.

The index
---------
:func:`run_bundle` returns the :class:`~hydromodpy.core.payload.PayloadBundle`
of one sealed run: every file the run read (``inputs.json``, then the files the
configuration declared), each with its destination relative to the workspace
(``data/<variable>/<name>``) or to the project, its variable, provider,
request, licence and the digest of its sidecar; the registry row of every
station series; the data cache row of every file a provider delivered; the
``[site]`` of the run. A declared folder is never copied whole: the files the
run read in it are.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

from hydromodpy.core.exceptions import ExportError
from hydromodpy.core.payload import (
    InstallIndex,
    PayloadBundle,
    PayloadFile,
    PayloadStation,
    payload_file_of,
    sidecar_name,
    stored_name,
)
from hydromodpy.core.payload.install import read_registry, sha256_of
from hydromodpy.core.site import SiteRow
from hydromodpy.core.state.paths import decode_workspace_path
from hydromodpy.core.workspace.resolve import locate_workspace_root
from hydromodpy.results.export.publish import MissingInputError
from hydromodpy.results.export.run_identity import read_sealed_manifest
from hydromodpy.results.manifest import InputEntry, ManifestSite
from hydromodpy.results.record import read_inputs
from hydromodpy.results.storage.attempt import is_run_product

DATA_DIRNAME: Final[str] = "data"
"""Folder of the workspace that holds the shared data."""

CUSTOM_PROVIDERS: Final[frozenset[str]] = frozenset({"custom", "constant", "synthetic"})
"""Providers whose files no cache row serves: a user file, a generated value."""

_SIDECAR_SUFFIX: Final[str] = ".json"
_LOC_SUFFIX: Final[str] = "_LOC.csv"


def run_bundle(run_dir: str | Path, *, project_root: str | Path) -> PayloadBundle:
    """Return the install index of one sealed run and the local files holding its bytes.

    Raises
    ------
    MissingInputError
        An input is not on disk any more.
    ExportError
        An input has no digest, another digest than the one sealed, or lies
        outside the workspace.
    """
    run = Path(run_dir)
    project = Path(project_root).resolve()
    workspace = locate_workspace_root(project) or project
    files: dict[tuple[str, str], PayloadFile] = {}
    blobs: dict[str, Path] = {}
    stations: dict[tuple[str, str], PayloadStation] = {}
    cache = _CacheRows(workspace)
    try:
        for entry in read_inputs(run).inputs:
            if not entry.path:
                raise ExportError(
                    f"input {entry.variable} ({entry.provider}) names no file in inputs.json: "
                    "its bytes cannot be carried. Run the configuration again to seal it "
                    "with the file it read."
                )
            located = _located(entry.path, entry.variable, workspace, project)
            item = _payload_file(entry, located, workspace, project, cache)
            _add(files, blobs, item, located)
            station = _station_row(item, located, workspace)
            if station is not None:
                stations[(station.dest, station.id)] = station
        seal = read_sealed_manifest(run)
        for tracked in seal.inputs if seal is not None else ():
            located = _located(tracked.path, tracked.role, workspace, project)
            if located.is_dir():
                continue
            if located.resolve() in {path.resolve() for path in blobs.values()}:
                continue
            _check_digest(located, tracked.sha256, tracked.role)
            item = _file_entry(
                located,
                workspace,
                project,
                sha256=tracked.sha256,
                provider="custom",
                license=None,
            )
            _add(files, blobs, item, located)
    finally:
        cache.close()
    site = None if seal is None else _site_row(seal.site)
    return PayloadBundle(
        index=InstallIndex(
            files=tuple(files[key] for key in sorted(files)),
            stations=tuple(stations[key] for key in sorted(stations)),
            sites=() if site is None else (site,),
        ),
        blobs=blobs,
    )


def inputs_of(project_root: str | Path) -> Callable[[Path], PayloadBundle]:
    """Return the builder ``publish(..., inputs=)`` calls on each run of *project_root*."""
    return functools.partial(run_bundle, project_root=project_root)


def _add(
    files: dict[tuple[str, str], PayloadFile],
    blobs: dict[str, Path],
    item: PayloadFile,
    located: Path,
) -> None:
    """Keep one entry per destination, and the local files of its bytes and sidecar."""
    files.setdefault((item.root, item.dest), item)
    blobs[stored_name(item.sha256, item.dest)] = located
    if item.sidecar_sha256 is not None:
        blobs[sidecar_name(item.sidecar_sha256)] = _sidecar_of(located)


def _located(path: str, name: str, workspace: Path, project: Path) -> Path:
    """Return the file an input names, relative to the workspace, or refuse a missing one."""
    candidate = decode_workspace_path(workspace, path)
    if candidate.exists():
        return candidate
    if is_run_product(path, project):
        raise MissingInputError(
            f"input {name}: {path} is a product the run derived in its scratch, which the "
            "seal removed. It is no input: the run was sealed by a release that recorded "
            "it as one. Run the configuration again to seal it with its real inputs.",
            derived=True,
        )
    raise MissingInputError(
        f"input {name}: {path} is not on disk any more, so it cannot be copied."
    )


def _check_digest(located: Path, sha256: str | None, name: str) -> str:
    """Return the digest of *located*, refusing one the run did not seal."""
    if sha256 is None:
        raise ExportError(
            f"input {name} ({located.name}) has no sha256 in the seal: its bytes cannot be "
            "addressed by content."
        )
    found = sha256_of(located)
    if found != sha256:
        raise ExportError(f"input {name}: {located.name} no longer has the digest the run sealed.")
    return found


def _payload_file(
    entry: InputEntry,
    located: Path,
    workspace: Path,
    project: Path,
    cache: _CacheRows,
) -> PayloadFile:
    """Return the index entry of one loaded input."""
    sha256 = _check_digest(located, entry.sha256, entry.variable)
    row = None if entry.provider in CUSTOM_PROVIDERS else cache.row_for(located)
    return _file_entry(
        located,
        workspace,
        project,
        sha256=sha256,
        provider=entry.provider,
        product=entry.product,
        license=entry.license,
        request=dict(entry.request) or None,
        cache=row,
    )


def _file_entry(
    located: Path,
    workspace: Path,
    project: Path,
    *,
    sha256: str,
    provider: str | None,
    license: str | None,
    product: str | None = None,
    request: Mapping[str, Any] | None = None,
    cache: Mapping[str, Any] | None = None,
) -> PayloadFile:
    """Return the entry of one file, its licence read from its sidecar when the seal has none."""
    if license is None:
        from hydromodpy.schema.sources import input_licence

        license = input_licence(located).spdx
    try:
        return payload_file_of(
            located,
            workspace=workspace,
            project=project,
            sha256=sha256,
            provider=provider,
            license=license,
            product=product,
            request=request,
            cache=cache,
        )
    except ValueError as exc:
        raise ExportError(f"input {exc}") from exc


def _sidecar_of(path: Path) -> Path:
    return path.with_name(path.name + _SIDECAR_SUFFIX)


def _station_row(item: PayloadFile, located: Path, workspace: Path) -> PayloadStation | None:
    """Return the registry row of a station series, read from ``<prefix>_<provider>_LOC.csv``.

    A station file carries values only: its coordinates, CRS and unit live in
    the registry beside it, and a load without that row fails.
    """
    station = (item.request or {}).get("station")
    if station is None or item.variable is None or item.provider is None:
        return None
    marker = f"_{item.provider}_"
    if marker not in located.name:
        return None
    prefix = located.name.split(marker, 1)[0]
    registry = located.with_name(f"{prefix}_{item.provider}{_LOC_SUFFIX}")
    _, rows = read_registry(registry)
    row = next((row for row in rows if row.get("id") == str(station)), None)
    if row is None:
        return None
    return PayloadStation(
        dest=registry.resolve().relative_to(workspace).as_posix(),
        row=tuple((key, value) for key, value in row.items()),
    )


def _site_row(site: ManifestSite | None) -> SiteRow | None:
    """Return the ``[site]`` of a run as a row of the site catalog."""
    if site is None:
        return None
    return SiteRow(
        site=site.name,
        label=site.label,
        gauge=site.gauge,
        uri=site.uri,
        x_outlet=site.x_outlet,
        y_outlet=site.y_outlet,
        crs=site.crs,
    )


class _CacheRows:
    """The data cache of the source workspace, opened read-only on first use."""

    _COLUMNS: Final[tuple[str, ...]] = (
        "variable",
        "source",
        "station_id",
        "crs",
        "date_start",
        "date_end",
        "frequency",
        "unit",
        "source_unit",
    )

    def __init__(self, workspace: Path) -> None:
        self._path = workspace / DATA_DIRNAME / "cache.duckdb"
        self._catalog: Any = None

    def row_for(self, located: Path) -> dict[str, Any] | None:
        """Return the cache row that serves *located*, or the key its sidecar states."""
        entry = self._entry(located)
        if entry is None:
            return _row_from_sidecar(located)
        row: dict[str, Any] = {key: _cell(getattr(entry, key)) for key in self._COLUMNS}
        bbox = [entry.bbox_xmin, entry.bbox_ymin, entry.bbox_xmax, entry.bbox_ymax]
        if all(value is not None for value in bbox):
            row["bbox"] = [float(value) for value in bbox]
        metadata = entry.fetch_metadata
        if isinstance(metadata, str) and metadata:
            row["fetch_metadata"] = json.loads(metadata)
        elif isinstance(metadata, dict):
            row["fetch_metadata"] = metadata
        return {key: value for key, value in row.items() if value is not None}

    def _entry(self, located: Path) -> Any:
        if not self._path.is_file():
            return None
        if self._catalog is None:
            from hydromodpy.data.registry import DataCatalogDuckDB

            self._catalog = DataCatalogDuckDB(self._path, read_only=True)
        return self._catalog.entry_for_file(located)

    def close(self) -> None:
        if self._catalog is not None:
            self._catalog.close()
            self._catalog = None


def _row_from_sidecar(located: Path) -> dict[str, Any] | None:
    """Return the cache key a sidecar states, for a file its workspace no longer indexes."""
    from hydromodpy.data.provenance.sidecars import load_sidecar

    try:
        sidecar = load_sidecar(located)
    except Exception:  # noqa: BLE001 - an unreadable sidecar states nothing
        return None
    if sidecar is None:
        return None
    row: dict[str, Any] = {
        "variable": sidecar.variable or located.parent.name,
        "source": sidecar.source,
        "crs": sidecar.crs,
        "date_start": sidecar.date_start,
        "date_end": sidecar.date_end,
        "frequency": sidecar.frequency,
        "unit": sidecar.unit,
        "source_unit": sidecar.source_unit,
    }
    if sidecar.bbox is not None:
        row["bbox"] = [float(value) for value in sidecar.bbox]
    return {key: value for key, value in row.items() if value is not None}


def _cell(value: Any) -> Any:
    """Return a cache cell as TOML writes it: a date as its ISO text."""
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else value


__all__ = [
    "CUSTOM_PROVIDERS",
    "DATA_DIRNAME",
    "inputs_of",
    "run_bundle",
]
