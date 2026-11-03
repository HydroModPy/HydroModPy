"""``hmp doctor`` - diagnose the local environment.

It reads and reports. The files it rewrites are the TOML that ``--fix-config``
names and the files it inherits through ``base_config``, migrated in place to
the current grammar. The workspace is the one ``-w`` names or the one that holds the current
directory, never a default folder: without one, the workspace checks say so
and name ``-w``.
"""

from __future__ import annotations

import argparse
import importlib
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from hydromodpy.cli.conventions import workspace_parser
from hydromodpy.cli.helpers import EXIT_GENERIC, find_workspace

NAME: str = "doctor"
HELP: str = "Diagnose the local environment (Python, deps, solvers, workspace)"


_CORE_DEPS = (
    "numpy",
    "pandas",
    "scipy",
    "duckdb",
    "zarr",
    "pyproj",
    "rasterio",
    "shapely",
    "xarray",
    "flopy",
    "pydantic",
    "pint",
    "matplotlib",
)

_OPTIONAL_DEPS = ("gmsh", "whitebox_workflows", "geopandas")

_SOLVER_BINARIES = ("mfnwt", "mf6", "mp6", "mp7", "mt3dusgs")

# The PRT model shipped with MODFLOW 6.5.0. Older executables resolve and run,
# but reject a PRT name file.
_PRT_MIN_MF6_VERSION = (6, 5, 0)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser()],
        epilog=(
            "Examples:\n  hmp doctor\n  hmp doctor -w ~/hydromodpy --json\n"
            "  hmp doctor --toml run.toml\n  hmp doctor --fix-config run.toml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--toml", default=None, help="Resolve the workspace from a project TOML")
    parser.add_argument("--json", action="store_true", help="Emit a JSON report")
    parser.add_argument(
        "--cross-catalog",
        action="store_true",
        help="Cross-check the sealed runs on disk against the index of each project",
    )
    parser.add_argument(
        "--lifecycle",
        action="store_true",
        help="Surface lifecycle issues (stale attempts, abandoned sessions, tmp files)",
    )
    parser.add_argument(
        "--prt",
        action="store_true",
        help="Check that the resolved MODFLOW 6 build supports particle tracking (PRT)",
    )
    parser.add_argument(
        "--fix-config",
        default=None,
        metavar="FILE.toml",
        help=(
            "Rewrite every old key of a TOML and of the files it inherits through base_config "
            "under its current name, in place, and print what changed in each file. Preserves "
            "comments and layout. A key that still loads warns and names this option."
        ),
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    fix_config = getattr(args, "fix_config", None)
    if fix_config is not None:
        _fix_config(fix_config)
        return

    workspace = find_workspace(args.workspace)
    report = _build_report(workspace, args.workspace, toml=args.toml)

    if getattr(args, "cross_catalog", False):
        report["checks"].extend(_cross_catalog_checks(workspace))
    if getattr(args, "lifecycle", False):
        report["checks"].extend(_lifecycle_checks(workspace))
    if getattr(args, "prt", False):
        report["checks"].extend(_prt_checks())

    if args.json:
        import json as _json

        print(_json.dumps(report, indent=2, default=str))
    else:
        _print_report(report)

    if any(entry.get("status") == "KO" for entry in report["checks"]):
        sys.exit(EXIT_GENERIC)


def _fix_config(toml_path: str) -> None:
    """Rewrite a TOML and the files it inherits under the current grammar."""
    from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND
    from hydromodpy.config.config_migration import fix_config_chain
    from hydromodpy.core.config_kit.base import CANNOT_REWRITE

    path = Path(toml_path).expanduser()
    try:
        chain = fix_config_chain(path)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except Exception as exc:  # noqa: BLE001 - surface a clean parse error
        print(f"Could not migrate {path}: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    for file, changes in chain.items():
        if not changes:
            print(f"{file} is already up to date.")
            continue
        untouched = all(CANNOT_REWRITE in change for change in changes)
        print(f"{'Left as it is' if untouched else 'Migrated'} {file}:")
        for change in changes:
            print(f"  - {change}")


def _build_report(
    workspace: Path | None, workspace_arg: str | None, *, toml: str | None = None
) -> dict:
    from hydromodpy.core.version import __version__ as hmp_version

    checks: list[dict] = []

    python_ok = sys.version_info >= (3, 11)
    checks.append(
        {
            "name": "python",
            "status": "OK" if python_ok else "KO",
            "detail": f"{platform.python_version()} ({sys.executable})",
            "hint": None if python_ok else "HydroModPy requires Python >= 3.11",
        }
    )

    checks.append(
        {
            "name": "platform",
            "status": "OK",
            "detail": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "hint": None,
        }
    )

    checks.append(
        {
            "name": "hydromodpy",
            "status": "OK",
            "detail": f"version {hmp_version}",
            "hint": None,
        }
    )

    for dep in _CORE_DEPS:
        try:
            mod = importlib.import_module(dep)
            version = getattr(mod, "__version__", "unknown")
            checks.append(
                {
                    "name": f"dep:{dep}",
                    "status": "OK",
                    "detail": f"{version}",
                    "hint": None,
                }
            )
        except ImportError as exc:
            checks.append(
                {
                    "name": f"dep:{dep}",
                    "status": "KO",
                    "detail": f"{exc}",
                    "hint": "pip install -e . (re-install editable)",
                }
            )

    for dep in _OPTIONAL_DEPS:
        try:
            mod = importlib.import_module(dep)
            version = getattr(mod, "__version__", "unknown")
            checks.append(
                {
                    "name": f"opt:{dep}",
                    "status": "OK",
                    "detail": f"{version}",
                    "hint": None,
                }
            )
        except ImportError:
            checks.append(
                {
                    "name": f"opt:{dep}",
                    "status": "WARN",
                    "detail": "not installed",
                    "hint": "optional",
                }
            )

    try:
        import duckdb  # noqa: F401

        checks.append(
            {
                "name": "duckdb:open",
                "status": "OK",
                "detail": "opens in-memory database",
                "hint": None,
            }
        )
    except Exception as exc:
        checks.append(
            {
                "name": "duckdb:open",
                "status": "KO",
                "detail": str(exc),
                "hint": "Reinstall duckdb",
            }
        )

    try:
        from hydromodpy.core.workspace.workspace import resolve_bin_path
        from hydromodpy.solver.modflow_common.binaries import (
            locate_solver_binary,
            read_manifest,
        )

        effective_bin = Path(resolve_bin_path())
    except Exception as exc:  # pragma: no cover - defensive
        effective_bin = None
        checks.append(
            {
                "name": "solver:bin_path",
                "status": "KO",
                "detail": f"bin path resolution failed: {exc}",
                "hint": "Reinstall hydromodpy",
            }
        )
    else:
        checks.append(
            {
                "name": "solver:bin_path",
                "status": "OK",
                "detail": str(effective_bin),
                "hint": None,
            }
        )
        manifest = read_manifest(effective_bin)
        if manifest:
            checks.append(
                {
                    "name": "solver:cache_version",
                    "status": "OK",
                    "detail": (
                        f"release={manifest.get('release')} "
                        f"downloaded_at={manifest.get('downloaded_at')}"
                    ),
                    "hint": "Run 'hmp install-binaries --upgrade' to refresh.",
                }
            )

    for binary in _SOLVER_BINARIES:
        located = None
        if effective_bin is not None:
            try:
                located = locate_solver_binary(effective_bin, binary)
            except Exception:
                located = None
        path_hit = shutil.which(binary)
        if located:
            checks.append(
                {
                    "name": f"solver:{binary}",
                    "status": "OK",
                    "detail": str(located),
                    "hint": None,
                }
            )
        elif path_hit:
            checks.append(
                {
                    "name": f"solver:{binary}",
                    "status": "OK",
                    "detail": f"{path_hit} (from PATH)",
                    "hint": None,
                }
            )
        else:
            checks.append(
                {
                    "name": f"solver:{binary}",
                    "status": "WARN",
                    "detail": "not cached, not on PATH",
                    "hint": (
                        f"Run 'hmp install-binaries --subset {binary}' "
                        "(or let the first simulation trigger a lazy download)."
                    ),
                }
            )

    for entry in _probe_workspace(workspace, workspace_arg, toml=toml):
        checks.append(entry)

    return {
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()}",
        "hydromodpy": hmp_version,
        "checks": checks,
    }


def _probe_workspace(ws: Path | None, workspace_arg: str | None, *, toml: str | None) -> list[dict]:
    try:
        from hydromodpy.core.state.paths import PROJECTS_DIRNAME, catalog_path_for
        from hydromodpy.core.workspace.config import WorkspaceConfig
        from hydromodpy.core.workspace.exceptions import WorkspaceError
    except Exception as exc:  # pragma: no cover
        return [
            {
                "name": "workspace",
                "status": "KO",
                "detail": f"workspace import failed: {exc}",
                "hint": "Reinstall hydromodpy",
            }
        ]

    if toml is not None:
        return _probe_from_toml(Path(toml).expanduser().resolve(), WorkspaceConfig, WorkspaceError)

    if ws is None:
        where = (
            f"{Path(workspace_arg).expanduser().resolve()} is not a workspace"
            if workspace_arg
            else f"no workspace at or above {Path.cwd().resolve()}"
        )
        return [
            {
                "name": "workspace",
                "status": "WARN",
                "detail": where,
                "hint": "Name one with -w, or run 'hmp workspace init <workspace>'",
            }
        ]
    from hydromodpy.core.state.paths import data_cache_path_for

    cache = data_cache_path_for(ws / "data")
    checks = [
        {
            "name": "workspace",
            "status": "OK",
            "detail": f"{ws}",
            "hint": None,
        },
        _path_check("data_dir", ws / "data"),
    ]
    project_roots = []
    projects_dir = ws / PROJECTS_DIRNAME
    standalone = not projects_dir.is_dir() and (catalog_path_for(ws)).is_file()
    if not standalone:
        # A standalone project owns its index at the root and has no
        # ``projects/`` tree, so reporting one as missing would be noise.
        checks.append(_path_check("projects_dir", projects_dir))
    checks.append(_path_check("data_cache", cache, required=False))
    if projects_dir.is_dir():
        project_roots.extend(p for p in sorted(projects_dir.iterdir()) if p.is_dir())
    elif standalone:
        project_roots.append(ws)
    for project_root in project_roots:
        checks.extend(_probe_result_storage(project_root))
    return checks


def _probe_result_storage(
    ws: Path,
    *,
    catalog_path: Path | None = None,
    runs_dir: Path | None = None,
) -> list[dict]:
    """Report on the catalog/Zarr/Parquet storage layout."""
    try:
        from hydromodpy.results.storage.diagnostics import diagnose_result_storage
    except Exception as exc:  # pragma: no cover - defensive
        return [
            {
                "name": "results:diagnostics",
                "status": "KO",
                "detail": f"storage diagnostics import failed: {exc}",
                "hint": "Reinstall hydromodpy",
            }
        ]
    return [
        diagnostic.to_check()
        for diagnostic in diagnose_result_storage(
            ws,
            catalog_path=catalog_path,
            runs_dir=runs_dir,
        )
    ]


def _probe_from_toml(toml_path: Path, WorkspaceConfig, WorkspaceError) -> list[dict]:
    if not toml_path.exists():
        return [
            {
                "name": "workspace",
                "status": "KO",
                "detail": f"TOML not found: {toml_path}",
                "hint": "Check the path passed to --toml",
            }
        ]
    try:
        from hydromodpy.core.state.paths import resolve_project_root
        from hydromodpy.core.toml_io.loader import load_toml_with_base_config
        from hydromodpy.core.toml_io.paths import resolve_declared_path

        raw = load_toml_with_base_config(toml_path)
        # Every relative path of a project is read from its root, the folder
        # that holds project.toml, and the loader sets project_root to it.
        base_dir = resolve_project_root(toml_path.parent)
        workspace_section = dict(raw.get("workspace", {}))
        for key in ("root", "catalog_path", "data_dir", "runs_dir"):
            if key in workspace_section and workspace_section[key] is not None:
                workspace_section[key] = str(
                    resolve_declared_path(workspace_section[key], base_dir=base_dir)
                )
        workspace_section["project_root"] = str(base_dir)
        cfg = WorkspaceConfig.model_validate(workspace_section)
    except WorkspaceError as exc:
        return [
            {
                "name": "workspace",
                "status": "KO",
                "detail": f"resolution failed for {toml_path}",
                "hint": str(exc),
            }
        ]
    except Exception as exc:  # pragma: no cover - defensive
        return [
            {
                "name": "workspace",
                "status": "KO",
                "detail": f"config load failed: {exc}",
                "hint": "Validate the TOML with `hmp config check`",
            }
        ]

    checks = [
        {
            "name": "workspace",
            "status": "OK",
            "detail": f"resolved via {cfg.resolution_source}",
            "hint": None,
        },
        _path_check("workspace_root", cfg.root),
        _path_check("catalog_path", cfg.catalog_path),
        _path_check("data_dir", cfg.data_dir),
        _path_check("runs_dir", cfg.runs_dir),
    ]
    checks.extend(
        _probe_result_storage(
            cfg.project_root,
            catalog_path=cfg.catalog_path,
            runs_dir=cfg.runs_dir,
        )
    )
    return checks


def _path_check(name: str, path: Path, *, required: bool = True) -> dict:
    if path.exists():
        status = "OK"
        detail = f"{path}"
        hint = None
    else:
        status = "WARN" if not required else "WARN"
        detail = f"{path} (missing)"
        hint = "Created lazily when first used" if not required else None
    return {"name": name, "status": status, "detail": detail, "hint": hint}


def _cross_catalog_checks(workspace: Path | None) -> list[dict]:
    """Compare the sealed runs on disk with the index of each project.

    Disk is the truth: a sealed run missing from its index, or an index row
    whose directory is gone, means the index is behind. Both are fixed by
    ``hmp catalog reindex``.
    """
    if workspace is None:
        return [
            {
                "name": "cross_catalog:workspace",
                "status": "WARN",
                "detail": "no workspace resolved",
                "hint": "Name one with -w",
            }
        ]

    import duckdb

    from hydromodpy.core.state.paths import catalog_path_for, project_roots_under
    from hydromodpy.results.catalog.federation import sealed_run_dirs

    projects = project_roots_under(workspace)
    unindexed_projects: list[str] = []
    missing_from_index = 0
    missing_on_disk = 0
    n_sealed = 0
    for project_root in projects:
        on_disk = {
            path.relative_to(project_root).as_posix() for path in sealed_run_dirs(project_root)
        }
        n_sealed += len(on_disk)
        catalog_path = catalog_path_for(project_root)
        if not catalog_path.is_file():
            if on_disk:
                unindexed_projects.append(project_root.name)
            continue
        try:
            conn = duckdb.connect(str(catalog_path), read_only=True)
        except duckdb.Error:
            unindexed_projects.append(project_root.name)
            continue
        try:
            rows = conn.execute("SELECT rel_dir FROM simulations").fetchall()
            indexed = {str(row[0]) for row in rows}
        except duckdb.Error:
            unindexed_projects.append(project_root.name)
            continue
        finally:
            conn.close()
        missing_from_index += len(on_disk - indexed)
        missing_on_disk += len(indexed - on_disk)

    hint = "Run 'hmp catalog reindex' in the project"
    return [
        {
            "name": "cross_catalog:projects_indexed",
            "status": "OK" if not unindexed_projects else "WARN",
            "detail": (
                f"{len(projects)} project(s) under {workspace}, "
                f"{len(unindexed_projects)} with sealed runs and no readable index"
                + (f" ({', '.join(sorted(unindexed_projects))})" if unindexed_projects else "")
            ),
            "hint": hint,
        },
        {
            "name": "cross_catalog:runs_vs_index",
            "status": "OK" if missing_from_index == 0 else "WARN",
            "detail": f"{n_sealed} sealed run(s) on disk, {missing_from_index} missing from an index",
            "hint": hint,
        },
        {
            "name": "cross_catalog:index_vs_runs",
            "status": "OK" if missing_on_disk == 0 else "WARN",
            "detail": f"{missing_on_disk} index row(s) whose directory is gone",
            "hint": hint,
        },
    ]


def _lifecycle_checks(workspace: Path | None) -> list[dict]:
    """Count stale attempts, abandoned or orphan sessions and tmp files, from the disk."""
    if workspace is None:
        return [
            {
                "name": "lifecycle:workspace",
                "status": "WARN",
                "detail": "no workspace resolved",
                "hint": "Name one with -w",
            }
        ]

    from hydromodpy.cli._workers.catalog import (
        ABANDONED_SESSION_MINUTES,
        abandoned_calibration_session_count,
        orphan_calibration_session_count,
        stale_running_sim_ids,
    )
    from hydromodpy.core.state.paths import project_roots_under
    from hydromodpy.results.outcome import DEFAULT_STALE_AFTER_S

    stale: list[str] = []
    orphan_sessions = 0
    abandoned_sessions = 0
    for project_root in project_roots_under(workspace):
        stale.extend(
            f"{project_root.name}/{rel_dir}" for rel_dir in stale_running_sim_ids(project_root)
        )
        orphan_sessions += orphan_calibration_session_count(project_root)
        abandoned_sessions += abandoned_calibration_session_count(project_root)

    tmp_files = sum(1 for _ in workspace.rglob("*.tmp-*"))
    stale_minutes = int(DEFAULT_STALE_AFTER_S // 60)
    return [
        {
            "name": "lifecycle:stale_attempts",
            "status": "OK" if not stale else "WARN",
            "detail": (
                f"{len(stale)} attempt(s) running with no heartbeat for >{stale_minutes} min"
                + (f": {', '.join(stale)}" if stale else "")
            ),
            "hint": "Run 'hmp catalog gc --apply' in the project to mark them aborted",
        },
        {
            "name": "lifecycle:abandoned_calibration_sessions",
            "status": "OK" if abandoned_sessions == 0 else "WARN",
            "detail": (
                f"{abandoned_sessions} calibration session(s) still running after "
                f"{ABANDONED_SESSION_MINUTES // 60} h with no outcome"
            ),
            "hint": "Run 'hmp catalog gc --apply' in the project to close them as aborted",
        },
        {
            "name": "lifecycle:orphan_calibration_sessions",
            "status": "OK" if orphan_sessions == 0 else "WARN",
            "detail": f"{orphan_sessions} calibration session(s) name a best run that is gone",
            "hint": "Restore the run from trash/ (hmp catalog restore) or delete the session",
        },
        {
            "name": "lifecycle:tmp_files",
            "status": "OK" if tmp_files == 0 else "WARN",
            "detail": f"{tmp_files} stale tmp-* file(s) on disk",
            "hint": "Run 'hmp catalog gc --apply' in the project to clean them up",
        },
    ]


def _locate_mf6() -> Path | None:
    """Return the ``mf6`` executable doctor would hand to a simulation."""
    try:
        from hydromodpy.core.workspace.workspace import resolve_bin_path
        from hydromodpy.solver.modflow_common.binaries import locate_solver_binary

        located = locate_solver_binary(Path(resolve_bin_path()), "mf6")
    except Exception:  # pragma: no cover - defensive, falls back to PATH
        located = None
    if located:
        return Path(located)
    path_hit = shutil.which("mf6")
    return Path(path_hit) if path_hit else None


def _mf6_version(executable: Path) -> tuple[str, tuple[int, ...] | None]:
    """Return the raw ``mf6 -v`` banner and its parsed (major, minor, patch)."""
    try:
        completed = subprocess.run(
            [str(executable), "-v"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"could not run {executable}: {exc}", None
    banner = (completed.stdout + completed.stderr).strip()
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", banner)
    if match is None:
        return banner, None
    return banner, tuple(int(group) for group in match.groups())


def _prt_checks() -> list[dict]:
    """Report whether the local MODFLOW 6 build can run a PRT model."""
    minimum = ".".join(str(part) for part in _PRT_MIN_MF6_VERSION)

    executable = _locate_mf6()
    if executable is None:
        return [
            {
                "name": "prt:mf6",
                "status": "KO",
                "detail": "not cached, not on PATH",
                "hint": "Run 'hmp install-binaries --mf6-prt'",
            }
        ]

    banner, version = _mf6_version(executable)
    checks = [
        {
            "name": "prt:mf6",
            "status": "OK",
            "detail": str(executable),
            "hint": None,
        }
    ]

    if version is None:
        checks.append(
            {
                "name": "prt:mf6_version",
                "status": "WARN",
                "detail": f"unreadable version banner: {banner or 'empty'}",
                "hint": f"PRT needs MODFLOW {minimum} or newer",
            }
        )
    else:
        readable = ".".join(str(part) for part in version)
        supported = version >= _PRT_MIN_MF6_VERSION
        checks.append(
            {
                "name": "prt:mf6_version",
                "status": "OK" if supported else "KO",
                "detail": f"{readable} (PRT needs >= {minimum})",
                "hint": None if supported else "Run 'hmp install-binaries --mf6-prt --upgrade'",
            }
        )

    try:
        import flopy

        has_prt = hasattr(flopy.mf6, "ModflowPrt")
    except ImportError as exc:
        checks.append(
            {
                "name": "prt:flopy",
                "status": "KO",
                "detail": f"{exc}",
                "hint": "pip install -e . (re-install editable)",
            }
        )
    else:
        checks.append(
            {
                "name": "prt:flopy",
                "status": "OK" if has_prt else "KO",
                "detail": (
                    "flopy.mf6.ModflowPrt available" if has_prt else "flopy.mf6.ModflowPrt missing"
                ),
                "hint": None if has_prt else "Upgrade flopy",
            }
        )
    return checks


def _print_report(report: dict) -> None:
    print(f"Python     : {report['python']}")
    print(f"Platform   : {report['platform']}")
    print(f"HydroModPy : {report['hydromodpy']}")
    print()
    print(f"{'STATUS':<6} {'CHECK':<28} DETAIL")
    print("-" * 70)
    for entry in report["checks"]:
        status = entry["status"]
        marker = {"OK": "OK", "WARN": "WARN", "KO": "KO"}.get(status, status)
        print(f"{marker:<6} {entry['name']:<28} {entry['detail']}")
        if entry.get("hint") and status != "OK":
            print(f"       -> {entry['hint']}")
