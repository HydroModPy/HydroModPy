"""Private worker helpers for ``hmp dev`` actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def export_schema(output_dir: Any) -> dict:
    """Export the HydroModPy JSON Schema + companion files for frontend hooks."""
    from hydromodpy.schema import export_full_schema

    out_path = Path(output_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    return export_full_schema(out_path)


def validate_field(path: str, value: str, *, context: dict | None = None) -> dict:
    """Validate one configuration field value without loading a full config."""
    from hydromodpy.schema import validate_field as _validate

    return _validate(path, value, context=context).as_dict()


def rank_simulations(
    project: str,
    *,
    workspace: Any = None,
    metric: str = "nse",
    top: bool = True,
    n: int = 5,
) -> Any:
    """Rank simulations of one project by a metric. Returns a DataFrame."""
    from hydromodpy.core.state.paths import resolve_project_root
    from hydromodpy.results.catalog import Catalog

    workspace_root = resolve_project_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    with Catalog(workspace_root, read_only=True) as catalog:
        order = "DESC" if top else "ASC"
        sql = (
            "SELECT s.sim_id, s.name, s.solver, m.metric_name, m.value "
            "FROM simulations s JOIN metrics m ON s.sim_id = m.sim_id "
            "WHERE s.project = ? AND m.metric_name = ? "
            f"ORDER BY m.value {order} LIMIT ?"
        )
        return catalog.connection.execute(sql, [project, metric, int(n)]).fetchdf()


def install_binaries(
    *,
    subset: list[str] | None = None,
    mf6_prt: bool = False,
    bindir: Any = None,
    upgrade: bool = False,
    quiet: bool = False,
    release: str | None = None,
) -> dict:
    """Pre-warm the MODFLOW / MODPATH / MT3D-USGS binary cache."""
    from hydromodpy.solver.modflow_common.binaries import (
        DEFAULT_RELEASE,
        available_solvers,
        download_solver_binaries,
        locate_solver_binary,
        managed_bin_dir,
        read_manifest,
    )

    target = Path(bindir).expanduser().resolve() if bindir else managed_bin_dir()
    resolved_release = release or DEFAULT_RELEASE

    if mf6_prt:
        names = ["mf6"]
    elif subset:
        names = list(subset)
    else:
        names = list(available_solvers())

    manifest = read_manifest(target)
    cached = (
        manifest is not None
        and manifest.get("release") == resolved_release
        and set(names).issubset(set(manifest.get("solvers", [])))
        and all(locate_solver_binary(target, name) is not None for name in names)
    )

    if cached and not upgrade:
        return {
            "already_cached": True,
            "release": resolved_release,
            "installed": [],
            "target": str(target),
        }

    final_target = download_solver_binaries(
        bindir=target,
        subset=names,
        quiet=quiet,
        force=upgrade,
        release=resolved_release,
    )
    return {
        "already_cached": False,
        "release": resolved_release,
        "installed": names,
        "target": str(final_target),
    }


def _lock_workspace_root(workspace: Any) -> Path:
    """Return the workspace root a lock command reads, which must already exist.

    :func:`hydromodpy.cli.helpers.resolve_workspace` prints and calls
    ``sys.exit`` on a missing root. A worker the Python API calls too must
    raise instead, and leave the exit code to ``cli/commands/``.
    """
    from hydromodpy.data.scaffold import DEFAULT_ROOT

    root = Path(workspace).expanduser().resolve() if workspace else DEFAULT_ROOT
    if not root.is_dir():
        raise FileNotFoundError(f"Workspace not found: {root}. Run 'hmp workspace init' first.")
    return root


def _lock_cache_database(workspace_root: Path) -> Path:
    """Return the cache database of a workspace, which must already exist.

    Locking an empty cache would pin nothing, so a missing database is an
    error instead of a file DuckDB creates on the way past.
    """
    db_path = workspace_root / "data" / "cache.duckdb"
    if not db_path.is_file():
        raise FileNotFoundError(f"Data cache not found: {db_path}")
    return db_path


def _lock_cache_workspace(project_root: Path) -> Path:
    """Return the workspace whose cache the lockfile of *project_root* pins.

    The workspace holding the project, the project itself when it carries the
    ``data/`` directory of a flat layout, else the default workspace.
    """
    from hydromodpy.cli.helpers import find_data_workspace

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
    from hydromodpy.data.data_freeze import project_lockfile_path, resolve_lockfile_root

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

    ``project_root`` travels with the write so this file carries the same
    ``[hydromodpy].project_git_commit`` as the one ``hmp run`` produces.
    """
    from hydromodpy.config.schema_export import schema_sha256
    from hydromodpy.data.data_freeze import write_lockfile
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.results.storage.parquet_schemas import PARQUET_SCHEMA_VERSION
    from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION

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


def lock_archive(output: Any, *, workspace: Any = None) -> Path:
    """Create a portable archive of the lockfile + cache artefacts."""
    from hydromodpy.data.data_freeze import archive_lockfile
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    db_path = _lock_cache_database(_lock_workspace_root(workspace))
    dest = Path(output).expanduser().resolve()
    with DataCatalogDuckDB(db_path) as catalog:
        archive_lockfile(catalog, dest)
    return dest


def lock_restore(source: Any, *, workspace: Any = None, output: Any = None) -> Path:
    """Restore a lockfile archive and verify SHA-256."""
    from hydromodpy.data.data_freeze import restore_archive

    workspace_root = _lock_workspace_root(workspace)
    src = Path(source).expanduser().resolve()
    dest_dir = (
        Path(output).expanduser().resolve() if output else (workspace_root / "data" / "restored")
    )
    restore_archive(src, dest_dir)
    return dest_dir


def lock_verify(
    workspace: Any = None,
    *,
    project: Any = None,
    lockfile: Any = None,
    strict: bool = False,
) -> dict:
    """Verify the cache matches the lockfile of one project."""
    from hydromodpy.config.schema_export import schema_sha256
    from hydromodpy.data.data_freeze import (
        read_lockfile_schema_sha256,
        verify_frozen,
        verify_inputs_strict,
    )
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

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


def config_template(
    output: Any,
    *,
    profile: str = "user",
    modules: list[str] | None = None,
    list_modules: bool = False,
) -> Any:
    """Generate a TOML configuration template (or list module names)."""
    from hydromodpy.config.template import generate_template, list_available_modules

    if list_modules:
        return list_available_modules()
    dest = Path(output).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    return generate_template(dest, profile=profile, modules=modules)


def config_check(toml_path: Any) -> dict:
    """Validate a TOML payload against the Pydantic schema."""
    from hydromodpy.config import HydroModPyConfig

    target = Path(toml_path).expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(f"Config not found: {target}")
    try:
        HydroModPyConfig.from_toml(target)
    except Exception as exc:  # noqa: BLE001 - surfaced to caller
        return {"path": str(target), "ok": False, "errors": [str(exc)]}
    return {"path": str(target), "ok": True, "errors": []}


def run_tests(
    *,
    fast: bool = False,
    integration: bool = False,
    validation: bool = False,
    e2e: bool = False,
    extra: list[str] | None = None,
) -> int:
    """Invoke pytest with matching markers. Returns the pytest exit code."""
    import subprocess
    import sys as _sys

    markers: list[str] = []
    if fast:
        markers.append("fast")
    if integration:
        markers.append("integration")
    if validation:
        markers.append("validation")
    if e2e:
        markers.append("e2e")
    cmd = [_sys.executable, "-m", "pytest"]
    if markers:
        cmd.extend(["-m", " or ".join(markers)])
    if extra:
        cmd.extend(extra)
    completed = subprocess.run(cmd, check=False)
    return completed.returncode
