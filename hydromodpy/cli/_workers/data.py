"""Private worker helpers for ``hmp data`` actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def list_data_cache(
    workspace: Any = None,
    *,
    variable: str | None = None,
    provider: str | None = None,
) -> Any:
    """List artefacts indexed in the workspace data cache."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    db_path = workspace_root / "data" / "cache.duckdb"
    if not db_path.exists():
        return None
    with DataCatalogDuckDB(db_path) as catalog:
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
    workspace: Any = None,
) -> dict:
    """Serve a data request into ``out`` and return its report.

    ``target`` is a request document (a ``.json`` file) or a variable name, in
    which case the request is built from the options. The cache is the
    workspace's when ``workspace`` is given, otherwise one in memory.
    """
    from hydromodpy.data import DataRequest, DataStore, run_request

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
    if workspace is not None:
        from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws

        store = DataStore(workspace_root=_resolve_ws(str(workspace)))
    report = run_request(request, Path(out).expanduser(), store=store)
    return report.to_document()


def check_data_cache(
    workspace: Any = None,
    *,
    variable: str | None = None,
    fix: bool = False,
) -> dict:
    """Validate custom files in ``data/<variable>/``. Returns issues + optional fix summary."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.data.workspace.custom_scan import check_custom

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    issues = check_custom(workspace_root, variable=variable)
    fix_summary: dict | None = None
    if fix:
        db_path = workspace_root / "data" / "cache.duckdb"
        if db_path.exists():
            with DataCatalogDuckDB(db_path) as catalog:
                fix_summary = catalog.check_and_fix()
    return {
        "workspace": str(workspace_root),
        "issues": [(str(path), str(msg)) for path, msg in issues],
        "fix_summary": fix_summary,
    }


def add_data_entry(
    file: Any,
    *,
    variable: str,
    provider: str = "custom",
    crs: str | None = None,
    unit: str | None = None,
    station_id: str | None = None,
    workspace: Any = None,
    project: Any = None,
    frozen: bool = False,
) -> dict:
    """Ingest a single file into the workspace data cache.

    ``frozen`` checks the candidate against the lockfile of ``project``, or of
    the project the current directory sits in when none is named. ``workspace``
    only ever names the cache the file lands in: it holds many projects and
    therefore no lockfile of its own.
    """
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.ingest import (
        convert_asc_to_geotiff,
        convert_timeseries_csv_to_parquet,
        convert_vector_to_geoparquet,
    )
    from hydromodpy.data.provenance.lockfile import (
        project_lockfile_path,
        read_lockfile,
        resolve_lockfile_root,
        sha256_of,
    )
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.data.workspace.scaffold import VARIABLES

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    src = Path(file).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"File not found: {src}")
    if frozen:
        lockfile = project_lockfile_path(resolve_lockfile_root(project))
        if not lockfile.is_file():
            raise FileNotFoundError(f"--frozen requested but no lockfile at {lockfile}")
        expected = {la.sha256 for la in read_lockfile(lockfile)}
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

    with DataCatalogDuckDB(workspace_root / "data" / "cache.duckdb") as catalog:
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
    workspace: Any = None,
    *,
    variable: str | None = None,
    provider: str | None = None,
    station_id: str | None = None,
    delete_files: bool = False,
) -> int:
    """Remove cache entries matching the filters. Returns the removed count."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    db_path = workspace_root / "data" / "cache.duckdb"
    if not db_path.exists():
        return 0
    with DataCatalogDuckDB(db_path) as catalog:
        return catalog.invalidate(
            variable=variable,
            source=provider,
            station_id=station_id,
            delete_files=delete_files,
        )


def prune_data_cache(
    workspace: Any = None,
    *,
    older_than_days: int = 30,
    delete_files: bool = False,
) -> int:
    """Drop cache entries older than N days. Returns the removed count."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    db_path = workspace_root / "data" / "cache.duckdb"
    if not db_path.exists():
        return 0
    with DataCatalogDuckDB(db_path) as catalog:
        return catalog.prune_older_than(days=older_than_days, delete_files=delete_files)


def archive_data_cache(output: Any, *, workspace: Any = None) -> Path:
    """Archive the workspace cache + lockfile to a portable file."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.data.registry.freeze import archive_lockfile

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    db_path = workspace_root / "data" / "cache.duckdb"
    dest = Path(output).expanduser().resolve()
    with DataCatalogDuckDB(db_path) as catalog:
        archive_lockfile(catalog, dest)
    return dest


def restore_data_cache(source: Any, *, workspace: Any = None) -> Path:
    """Restore a cache archive into the workspace. Returns destination path."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.registry.freeze import restore_archive

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    src = Path(source).expanduser().resolve()
    dest = workspace_root / "data" / "imported"
    restore_archive(src, dest)
    return dest


def import_package(
    package: Any,
    *,
    workspace: Any = None,
    as_project: str | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> str:
    """Import a ``.hmp`` archive into a workspace catalog. Returns the sim_id."""
    from hydromodpy.results.catalog import Catalog

    src = Path(package).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"Archive not found: {src}")
    workspace_root = Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    with Catalog(workspace_root) as catalog:
        return catalog.import_package(src, force=force, as_project=as_project, dry_run=dry_run)
