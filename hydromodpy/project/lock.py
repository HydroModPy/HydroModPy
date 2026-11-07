"""The lockfile of a project: ``hmp lock update``, ``hmp lock verify`` and the cache archive.

It reads ``data``, ``results`` (two schema versions) and ``schema``, which only
``project`` may do together.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.state.layout import data_cache_path_for
from hydromodpy.core.workspace.resolve import find_data_workspace, find_workspace


def _lock_workspace_root(workspace: Any) -> Path:
    """Return the workspace root a lock command reads, which must already exist.

    :func:`hydromodpy.cli.helpers.resolve_workspace` prints and calls
    ``sys.exit`` on a missing root. A function the Python API calls too must
    raise instead, and leave the exit code to ``cli/commands/``.
    """
    root = find_workspace(str(workspace) if workspace else None)
    if root is None:
        raise FileNotFoundError(
            "No HydroModPy workspace found. Name one with -w, or run hmp workspace init."
        )
    return root


def _lock_cache_database(workspace_root: Path) -> Path:
    """Return the cache database of a workspace, which must already exist.

    Locking an empty cache would pin nothing, so a missing database is an
    error instead of a file DuckDB creates on the way past.
    """
    db_path = data_cache_path_for(workspace_root / "data")
    if not db_path.is_file():
        raise FileNotFoundError(f"Data cache not found: {db_path}")
    return db_path


def _lock_cache_workspace(project_root: Path) -> Path:
    """Return the workspace whose cache the lockfile of *project_root* pins.

    The workspace holding the project, the project itself when it carries the
    ``data/`` directory of a flat layout, else the workspace above the cwd.
    """
    found = find_data_workspace(project_root)
    if found is not None:
        return found
    if (project_root / "data").is_dir():
        return project_root
    return _lock_workspace_root(None)


def _lock_targets(workspace: Any, project: Any, lockfile: Any) -> tuple[Path, Path, Path]:
    """Return the cache database, the lockfile address and the project it describes.

    An explicit lockfile path is itself the address, so it needs no project
    root: the project it describes is the one named, or the directory the file
    lives in, since that is where a lockfile belongs. Only a derived address
    asks :func:`resolve_lockfile_root` for a root, and that is the call that
    refuses to answer outside a project.
    """
    from hydromodpy.data.provenance.lockfile import project_lockfile_path, resolve_lockfile_root

    explicit = Path(lockfile).expanduser().resolve() if lockfile else None
    if project:
        named = resolve_lockfile_root(project)
    elif explicit is not None:
        named = explicit.parent
    else:
        named = resolve_lockfile_root(None)
    workspace_root = _lock_workspace_root(workspace) if workspace else _lock_cache_workspace(named)
    return (
        _lock_cache_database(workspace_root),
        explicit if explicit is not None else project_lockfile_path(named),
        named,
    )


def lock_update(workspace: Any = None, *, project: Any = None, output: Any = None) -> Path:
    """Scan the cache and write/update the lockfile of one project.

    ``project_root`` travels with the write so the file carries the
    ``[hydromodpy].project_git_commit`` of the project it describes.
    """
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.data.registry.freeze import write_lockfile
    from hydromodpy.results.storage.parquet_schemas import PARQUET_SCHEMA_VERSION
    from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION
    from hydromodpy.schema.config_schema import schema_sha256

    db_path, dest, project_root = _lock_targets(workspace, project, output)
    with DataCatalogDuckDB(db_path) as catalog:
        return write_lockfile(
            catalog,
            dest,
            project_root=project_root,
            schema_sha256=schema_sha256(),
            zarr_schema_version=str(ZARR_SCHEMA_VERSION),
            parquet_schema_version=str(PARQUET_SCHEMA_VERSION),
        )


def lock_verify(
    workspace: Any = None,
    *,
    project: Any = None,
    lockfile: Any = None,
    strict: bool = False,
) -> dict:
    """Verify the cache matches the lockfile of one project."""
    from hydromodpy.data.provenance.lockfile import read_lockfile_schema_sha256
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.data.registry.freeze import verify_frozen, verify_inputs_strict
    from hydromodpy.schema.config_schema import schema_sha256

    db_path, lockfile_path, _ = _lock_targets(workspace, project, lockfile)
    if not lockfile_path.is_file():
        raise FileNotFoundError(f"Lockfile not found: {lockfile_path}")

    locked_schema = read_lockfile_schema_sha256(lockfile_path)
    current_schema = schema_sha256()
    schema_diverged = locked_schema is not None and locked_schema != current_schema

    with DataCatalogDuckDB(db_path) as catalog:
        mismatches = (
            verify_inputs_strict(catalog, lockfile_path)
            if strict
            else verify_frozen(catalog, lockfile_path)
        )
    return {
        "ok": not mismatches,
        "mismatches": mismatches,
        "schema_diverged": schema_diverged,
        "locked_schema": locked_schema,
        "current_schema": current_schema,
    }


def archive_data_cache(output: Any, *, workspace_root: Path) -> Path:
    """Archive the workspace cache + lockfile to a portable file."""
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.data.registry.freeze import archive_lockfile
    from hydromodpy.results.storage.parquet_schemas import PARQUET_SCHEMA_VERSION
    from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION

    db_path = data_cache_path_for(workspace_root / "data")
    dest = Path(output).expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f"no data cache at {db_path}: nothing to archive")
    with DataCatalogDuckDB(db_path, read_only=True) as catalog:
        archive_lockfile(
            catalog,
            dest,
            zarr_schema_version=str(ZARR_SCHEMA_VERSION),
            parquet_schema_version=str(PARQUET_SCHEMA_VERSION),
        )
    return dest


def restore_data_cache(source: Any, *, workspace_root: Path, to: Any = None) -> Path:
    """Restore a cache archive and verify its SHA-256. Returns the destination.

    The destination is *to*, else ``data/imported`` of the workspace.
    """
    from hydromodpy.data.registry.freeze import restore_archive

    src = Path(source).expanduser().resolve()
    dest = Path(to).expanduser().resolve() if to else workspace_root / "data" / "imported"
    restore_archive(src, dest)
    return dest
