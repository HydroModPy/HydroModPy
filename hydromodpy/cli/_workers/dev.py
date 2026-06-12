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
    from hydromodpy.cli.helpers import find_catalog_root
    from hydromodpy.results.catalog import Catalog

    workspace_root = find_catalog_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    with Catalog(workspace_root) as catalog:
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


def lock_update(workspace: Any = None, *, output: Any = None) -> Path:
    """Scan the cache and write/update the workspace lockfile."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.config.schema_export import schema_sha256
    from hydromodpy.data.data_freeze import LOCKFILE_NAME, write_lockfile
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.results.parquet_schemas import PARQUET_SCHEMA_VERSION
    from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    db_path = workspace_root / "data" / "cache.duckdb"
    dest = Path(output).expanduser().resolve() if output else (workspace_root / LOCKFILE_NAME)
    with DataCatalogDuckDB(db_path) as catalog:
        return write_lockfile(
            catalog,
            dest,
            schema_sha256=schema_sha256(),
            zarr_schema_version=str(ZARR_SCHEMA_VERSION),
            parquet_schema_version=str(PARQUET_SCHEMA_VERSION),
        )


def lock_archive(output: Any, *, workspace: Any = None) -> Path:
    """Create a portable archive of the lockfile + cache artefacts."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.data_freeze import archive_lockfile
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    db_path = workspace_root / "data" / "cache.duckdb"
    dest = Path(output).expanduser().resolve()
    with DataCatalogDuckDB(db_path) as catalog:
        archive_lockfile(catalog, dest)
    return dest


def lock_restore(source: Any, *, workspace: Any = None, output: Any = None) -> Path:
    """Restore a lockfile archive and verify SHA-256."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.data_freeze import restore_archive

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    src = Path(source).expanduser().resolve()
    dest_dir = (
        Path(output).expanduser().resolve() if output else (workspace_root / "data" / "restored")
    )
    restore_archive(src, dest_dir)
    return dest_dir


def lock_verify(
    workspace: Any = None,
    *,
    lockfile: Any = None,
    strict: bool = False,
) -> dict:
    """Verify the cache matches the lockfile."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.config.schema_export import schema_sha256
    from hydromodpy.data.data_freeze import (
        LOCKFILE_NAME,
        read_lockfile_schema_sha256,
        verify_frozen,
        verify_inputs_strict,
    )
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    db_path = workspace_root / "data" / "cache.duckdb"
    lockfile_path = (
        Path(lockfile).expanduser().resolve() if lockfile else (workspace_root / LOCKFILE_NAME)
    )
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
