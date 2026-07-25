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


def fetch_data_variable(
    variable: str,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    workspace: Any = None,
    source: str = "upstream",
) -> dict:
    """Fetch an upstream variable into the cache and write a sidecar.

    Not implemented: no upstream provider fetch exists yet. The verb is gated
    with a clear error so it never silently writes a placeholder file that
    looks like real, checksummed data.
    """
    del bbox, workspace, source  # accepted for the eventual provider fetch

    from hydromodpy.data.scaffold import VARIABLES

    spec = next((s for s in VARIABLES if s.name == variable), None)
    if spec is None:
        raise ValueError(f"Unknown variable {variable!r}")

    raise NotImplementedError(
        f"'hmp data get {variable}' is not implemented yet: HydroModPy has no "
        f"upstream provider fetch. Place the file in data/{spec.name}/ using the "
        f"naming convention, or ingest an existing file with 'hmp data add'."
    )


def check_data_cache(
    workspace: Any = None,
    *,
    variable: str | None = None,
    fix: bool = False,
) -> dict:
    """Validate custom files in ``data/<variable>/``. Returns issues + optional fix summary."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.auto_scan import check_custom
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

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
    frozen: bool = False,
) -> dict:
    """Ingest a single file into the workspace data cache."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.adapters import (
        convert_asc_to_geotiff,
        convert_timeseries_csv_to_parquet,
        convert_vector_to_geoparquet,
    )
    from hydromodpy.data.data_freeze import LOCKFILE_NAME, read_lockfile, sha256_of
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.data.scaffold import VARIABLES

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    src = Path(file).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"File not found: {src}")
    if frozen:
        lockfile = workspace_root / LOCKFILE_NAME
        if not lockfile.is_file():
            raise FileNotFoundError(f"--frozen requested but no {lockfile}")
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
    from hydromodpy.data.data_freeze import archive_lockfile
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    db_path = workspace_root / "data" / "cache.duckdb"
    dest = Path(output).expanduser().resolve()
    with DataCatalogDuckDB(db_path) as catalog:
        archive_lockfile(catalog, dest)
    return dest


def restore_data_cache(source: Any, *, workspace: Any = None) -> Path:
    """Restore a cache archive into the workspace. Returns destination path."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.data_freeze import restore_archive

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


def export_simulation_package(
    sim_ref: str,
    *,
    output: Any,
    workspace: Any = None,
    project: str | None = None,
) -> Path:
    """Export a simulation as a portable ``.hmp`` archive."""
    from hydromodpy.core.state.paths import catalog_path_for
    from hydromodpy.results.catalog import Catalog

    workspace_root = Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    if not (catalog_path_for(workspace_root)).exists():
        raise FileNotFoundError(f"No catalog found at {workspace_root}")
    output_path = Path(output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Catalog(workspace_root) as catalog:
        sim_id = catalog.resolve(sim_ref, project=project)
        return catalog.export_package(sim_id, output_path)
