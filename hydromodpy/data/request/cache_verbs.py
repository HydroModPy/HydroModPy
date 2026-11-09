"""Verbs of ``hmp data`` on the cache of a workspace: list, request, remove, archive.

The cache is the sidecar next to each fetched file, so a verb reads it by a walk
of ``data/`` and writes only sidecars and the files they describe. A file the user
keeps under ``inputs/`` is no row, so no verb here touches it.
Each function takes the root of a workspace that is already resolved.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.data.provenance.sidecars import CacheIndex, ScanReport, scan

if TYPE_CHECKING:
    from hydromodpy.core.runtime.bounds import Bounds

DATA_DIRNAME = "data"


def list_data_cache(
    workspace_root: Path,
    *,
    variable: str | None = None,
    provider: str | None = None,
) -> ScanReport | None:
    """List the rows of the workspace data cache, or return None when there is no ``data/``.

    The report holds only the rows of *variable* and *provider* when they are given,
    and the sidecars the walk could not turn into a row.
    """
    data_root = Path(workspace_root) / DATA_DIRNAME
    if not data_root.is_dir():
        return None
    report = scan(data_root)
    rows = tuple(
        row
        for row in report.rows
        if (variable is None or row.variable == variable)
        and (provider is None or row.source == provider)
    )
    return replace(report, rows=rows)


def request_data(
    target: str,
    *,
    out: Any,
    bbox: tuple[float, float, float, float] | None = None,
    crs: str | None = None,
    mask: Any = None,
    stations: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    source: str | None = None,
    workspace_root: Path | None = None,
    environment_bounds: Bounds | None = None,
) -> dict:
    """Serve a data request into ``out`` and return its report.

    ``target`` is a request document (a ``.json`` file) or a variable name, in
    which case the request is built from the options. The cache is the
    workspace's when ``workspace_root`` is given, otherwise one in
    memory. ``environment_bounds`` are the bounds of the call that
    asked for data, so the fetcher refuses the hosts they do not allow;
    the object they come from never enters this package.
    """
    from hydromodpy.data.loading.store import DataStore
    from hydromodpy.data.request.engine import run_request
    from hydromodpy.data.request.model import DataRequest

    document = Path(target).expanduser()
    if document.suffix.lower() == ".json" and document.is_file():
        request = DataRequest.model_validate_json(document.read_text(encoding="utf-8"))
    else:
        request = DataRequest.for_variable(
            target,
            source=source,
            bbox=bbox,
            crs=crs,
            mask=mask,
            station_ids=stations,
            start=start,
            end=end,
        )
    store = None
    if workspace_root is not None:
        store = DataStore(
            workspace_root=workspace_root,
            bounds=environment_bounds,
        )
    report = run_request(
        request,
        Path(out).expanduser(),
        store=store,
        bounds=environment_bounds,
    )
    return report.to_document()


def remove_data_entries(
    workspace_root: Path,
    *,
    variable: str | None = None,
    provider: str | None = None,
    station_id: str | None = None,
    delete_files: bool = False,
    dry_run: bool = False,
) -> int:
    """Remove cache rows matching the filters. Returns the count, removed or found.

    A row is its sidecar. Without *delete_files* only the sidecar goes, and the file
    is then no row of the cache.
    """
    index = CacheIndex(Path(workspace_root) / DATA_DIRNAME)
    rows = index.rows(variable=variable, source=provider, station_id=station_id)
    if not dry_run:
        for row in rows:
            index.forget(row, delete_file=delete_files)
    return len(rows)


def archive_data_cache(output: str | Path, *, workspace_root: Path) -> Path:
    """Archive the rows of the workspace cache, each with its sidecar, and their lockfile."""
    from hydromodpy.data.provenance.archive import archive_data

    data_root = Path(workspace_root) / DATA_DIRNAME
    dest = Path(output).expanduser().resolve()
    if not scan(data_root).rows:
        raise FileNotFoundError(f"no data cache row under {data_root}: nothing to archive")
    return archive_data(data_root, dest)


def restore_data_cache(
    source: str | Path, *, workspace_root: Path, to: str | Path | None = None
) -> Path:
    """Restore a cache archive, each file with its sidecar, once its SHA-256 are checked.

    Returns the folder restored into: *to*, else ``data/`` of the workspace, where the
    restored files are rows of the cache at once.
    """
    from hydromodpy.data.provenance.archive import restore_archive

    src = Path(source).expanduser().resolve()
    dest = Path(to).expanduser().resolve() if to else Path(workspace_root) / DATA_DIRNAME
    restore_archive(src, dest)
    return dest
