"""Verbs of ``hmp data`` on the workspace cache: list, request, add, remove, prune.

A read (``ls``) opens the workspace cache read-only, so it never waits on, nor
blocks, a launch that merges into the cache. Only the actions that change the
cache (``add``, ``remove``, ``prune``) open it read-write.
Each function takes the root of a workspace that is already resolved.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.state.layout import data_cache_path_for

if TYPE_CHECKING:
    from hydromodpy.core.runtime.bounds import Bounds


def list_data_cache(
    workspace_root: Path,
    *,
    variable: str | None = None,
    provider: str | None = None,
) -> Any:
    """List artifacts indexed in the workspace data cache."""
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    db_path = data_cache_path_for(workspace_root / "data")
    if not db_path.exists():
        return None
    with DataCatalogDuckDB(db_path, read_only=True) as catalog:
        return catalog.list_entries(variable=variable, source=provider)


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


def add_data_entry(
    file: Any,
    *,
    variable: str,
    provider: str = "custom",
    crs: str | None = None,
    unit: str | None = None,
    station_id: str | None = None,
    workspace_root: Path,
    project: Any = None,
    frozen: bool = False,
) -> dict:
    """Ingest a single file into the workspace data cache.

    ``frozen`` checks the candidate against the lockfile of ``project``, or of
    the project the current directory sits in when none is named. ``workspace_root``
    only ever names the cache the file lands in: it holds many projects and
    therefore no lockfile of its own.
    """
    from hydromodpy.data.ingest import (
        convert_asc_to_geotiff,
        convert_timeseries_csv_to_parquet,
        convert_vector_to_geoparquet,
    )
    from hydromodpy.data.provenance.lockfile import (
        project_lockfile_path,
        read_lockfile_inputs,
        resolve_lockfile_root,
        sha256_of,
    )
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.data.workspace.scaffold import VARIABLES

    src = Path(file).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"File not found: {src}")
    if frozen:
        lockfile = project_lockfile_path(resolve_lockfile_root(project))
        if not lockfile.is_file():
            raise FileNotFoundError(f"--frozen requested but no lockfile at {lockfile}")
        expected = {item.sha256 for item in read_lockfile_inputs(lockfile)}
        if sha256_of(src) not in expected:
            raise ValueError(f"--frozen: {src} SHA-256 does not match any lockfile entry")

    spec = next((s for s in VARIABLES if s.name == variable), None)
    if spec is None:
        raise ValueError(f"Unknown variable {variable!r}")

    blobs = workspace_root / "data" / "blobs" / spec.name / provider
    blobs.mkdir(parents=True, exist_ok=True)
    if spec.kind == "timeseries":
        sid = station_id or src.stem
        dest = blobs / f"{sid}.parquet"
        convert_timeseries_csv_to_parquet(src, dest)
    elif spec.kind == "raster":
        sid = None
        dest = blobs / f"{src.stem}.tif"
        convert_asc_to_geotiff(src, dest)
    elif spec.kind == "vector":
        sid = None
        dest = blobs / f"{src.stem}.parquet"
        convert_vector_to_geoparquet(src, dest)
    else:
        raise ValueError(f"Unsupported kind {spec.kind!r}")

    with DataCatalogDuckDB(data_cache_path_for(workspace_root / "data")) as catalog:
        catalog.register(
            variable=spec.name,
            source=provider,
            station_id=sid,
            file_path=str(src),
            crs=crs,
            unit=unit or spec.unit,
            is_custom=True,
            fetch_metadata={"pivot_path": str(dest), "pivot_format": spec.pivot},
        )
    return {"variable": spec.name, "provider": provider, "station_id": sid, "dest": str(dest)}


def remove_data_entries(
    workspace_root: Path,
    *,
    variable: str | None = None,
    provider: str | None = None,
    station_id: str | None = None,
    delete_files: bool = False,
    dry_run: bool = False,
) -> int:
    """Remove cache entries matching the filters. Returns the count, removed or found."""
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    db_path = data_cache_path_for(workspace_root / "data")
    if not db_path.exists():
        return 0
    with DataCatalogDuckDB(db_path) as catalog:
        return catalog.invalidate(
            variable=variable,
            source=provider,
            station_id=station_id,
            delete_files=delete_files,
            dry_run=dry_run,
        )


def prune_data_cache(
    workspace_root: Path,
    *,
    older_than_days: int = 30,
    delete_files: bool = False,
    dry_run: bool = False,
) -> int:
    """Drop cache entries older than N days. Returns the count, removed or found."""
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    db_path = data_cache_path_for(workspace_root / "data")
    if not db_path.exists():
        return 0
    with DataCatalogDuckDB(db_path) as catalog:
        return catalog.prune_older_than(
            days=older_than_days, delete_files=delete_files, dry_run=dry_run
        )
