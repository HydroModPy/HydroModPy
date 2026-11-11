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
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.cli.conventions import dry_run_parser, format_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_GENERIC, EXIT_USAGE, refuse
from hydromodpy.cli.output import emit
from hydromodpy.core.workspace.resolve import find_workspace

if TYPE_CHECKING:
    from hydromodpy.core.diagnostic import Diagnostic

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
        parents=[workspace_parser(), dry_run_parser(), format_parser()],
        epilog=(
            "Examples:\n  hmp doctor\n  hmp doctor -w ~/hydromodpy --format json\n"
            "  hmp doctor --fix-config run.toml\n"
            "The workspace a TOML file resolves to: hmp config check run.toml -v"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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
            "comments and layout. A key that still loads warns and names this option. "
            "With --dry-run it prints the diff it would write and writes nothing."
        ),
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    fix_config = getattr(args, "fix_config", None)
    if fix_config is not None:
        _fix_config(fix_config, dry_run=args.dry_run)
        return
    if args.dry_run:
        refuse("--dry-run goes with --fix-config: the other checks write nothing.", EXIT_USAGE)

    workspace = find_workspace(args.workspace)
    report = _build_report(workspace, args.workspace)

    if getattr(args, "cross_catalog", False):
        report["checks"].extend(_cross_catalog_checks(workspace))
    if getattr(args, "lifecycle", False):
        report["checks"].extend(_lifecycle_checks(workspace))
    if getattr(args, "prt", False):
        report["checks"].extend(_prt_checks())

    emit(args, "doctor", report, table=lambda: _print_report(report))

    if any(entry.get("status") == "KO" for entry in report["checks"]):
        sys.exit(EXIT_GENERIC)


def _fix_config(toml_path: str, *, dry_run: bool = False) -> None:
    """Rewrite a TOML and the files it inherits under the current grammar."""
    from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND
    from hydromodpy.config.config_migration import fix_config_chain
    from hydromodpy.core.config_kit.base import CANNOT_REWRITE

    path = Path(toml_path).expanduser()
    diffs: dict[Path, str] = {}
    try:
        chain = fix_config_chain(path, dry_run=dry_run, diffs=diffs)
    except FileNotFoundError as exc:
        refuse(str(exc), EXIT_NOT_FOUND, cause=exc)
    except Exception as exc:  # noqa: BLE001 - surface a clean parse error
        refuse(f"Could not migrate {path}: {exc}", EXIT_CONFIG, cause=exc)

    refused: Exception | None = None
    for file, changes in chain.items():
        if not changes:
            held = _checked(file)
            refusal = _refusal_in(held)
            if refusal is not None:
                print(f"{file} has nothing to migrate, and the check still refuses it:")
                print(f"  - {refusal}")
                refused = refusal
                continue
            # Under --dry-run the files above are not rewritten yet, so their old forms
            # still show here and are told under their own file.
            left = [] if dry_run else [item for item in held if item.code == "old_key"]
            if left:
                print(f"{file} has nothing to migrate, and the check still reads old forms:")
                for item in left:
                    print(f"  - {item.detail}")
            else:
                print(f"{file} is already up to date.")
            continue
        untouched = all(CANNOT_REWRITE in change for change in changes)
        label = "Left as it is" if untouched else ("Would migrate" if dry_run else "Migrated")
        print(f"{label} {file}:")
        for change in changes:
            print(f"  - {change}")
        if dry_run and diffs.get(file):
            print(diffs[file], end="" if diffs[file].endswith("\n") else "\n")
    if refused is not None:
        sys.exit(EXIT_CONFIG)


def _checked(file: Path) -> list[Diagnostic]:
    """Return what the check of ``config`` says of *file* and the files it inherits.

    A file that does not read as TOML is the business of the loader, not of the
    doctor, so it has no diagnostic here.
    """
    from hydromodpy.config.check import check
    from hydromodpy.core.toml_io.loader import config_base_dir, merge_toml_chain, read_toml_chain

    try:
        document = merge_toml_chain(read_toml_chain(file, root=None), root=None)
    except (ValueError, OSError):
        return []
    return check(document, partial=True, base=config_base_dir(file))


def _refusal_in(held: Sequence[Diagnostic]) -> Exception | None:
    """Return the refusal made of the ``retired_key`` diagnostics of *held*, else ``None``."""
    from hydromodpy.core.exceptions import ConfigValidationError

    retired = [item for item in held if item.code == "retired_key"]
    if not retired:
        return None
    return ConfigValidationError("\n".join(item.detail for item in retired), diagnostics=retired)


def _refusal_of(file: Path) -> Exception | None:
    """Return what the check says of *file* when it refuses a retired key, else ``None``.

    A partial file is refused for reasons that are not a retired key, and only a
    key the loader no longer accepts is the doctor's business.
    """
    return _refusal_in(_checked(file))


def _check(name: str, status: str, detail: str, hint: str | None = None) -> dict:
    """One row of the report: a name, OK, WARN or KO, what was seen, and what to do."""
    return {"name": name, "status": status, "detail": detail, "hint": hint}


def _build_report(workspace: Path | None, workspace_arg: str | None) -> dict:
    from hydromodpy.core.version import __version__ as hmp_version

    checks: list[dict] = []

    python_ok = sys.version_info >= (3, 11)
    checks.append(
        _check(
            "python",
            "OK" if python_ok else "KO",
            f"{platform.python_version()} ({sys.executable})",
            None if python_ok else "HydroModPy requires Python >= 3.11",
        )
    )

    checks.append(
        _check("platform", "OK", f"{platform.system()} {platform.release()} ({platform.machine()})")
    )

    checks.append(_check("hydromodpy", "OK", f"version {hmp_version}"))

    for dep in _CORE_DEPS:
        try:
            mod = importlib.import_module(dep)
            version = getattr(mod, "__version__", "unknown")
            checks.append(_check(f"dep:{dep}", "OK", f"{version}"))
        except ImportError as exc:
            checks.append(
                _check(f"dep:{dep}", "KO", f"{exc}", "pip install -e . (re-install editable)")
            )

    for dep in _OPTIONAL_DEPS:
        try:
            mod = importlib.import_module(dep)
            version = getattr(mod, "__version__", "unknown")
            checks.append(_check(f"opt:{dep}", "OK", f"{version}"))
        except ImportError:
            checks.append(_check(f"opt:{dep}", "WARN", "not installed", "optional"))

    try:
        import duckdb  # noqa: F401

        checks.append(_check("duckdb:open", "OK", "opens in-memory database"))
    except Exception as exc:
        checks.append(_check("duckdb:open", "KO", str(exc), "Reinstall duckdb"))

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
            _check(
                "solver:bin_path",
                "KO",
                f"bin path resolution failed: {exc}",
                "Reinstall hydromodpy",
            )
        )
    else:
        checks.append(_check("solver:bin_path", "OK", str(effective_bin)))
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
            checks.append(_check(f"solver:{binary}", "OK", str(located)))
        elif path_hit:
            checks.append(_check(f"solver:{binary}", "OK", f"{path_hit} (from PATH)"))
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

    for entry in _probe_workspace(workspace, workspace_arg):
        checks.append(entry)

    return {
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()}",
        "hydromodpy": hmp_version,
        "checks": checks,
    }


def _probe_workspace(ws: Path | None, workspace_arg: str | None) -> list[dict]:
    try:
        from hydromodpy.core.state.layout import PROJECTS_DIRNAME, catalog_path_for
    except Exception as exc:  # pragma: no cover
        return [
            _check("workspace", "KO", f"workspace import failed: {exc}", "Reinstall hydromodpy")
        ]

    if ws is None:
        where = (
            f"{Path(workspace_arg).expanduser().resolve()} is not a workspace"
            if workspace_arg
            else f"no workspace at or above {Path.cwd().resolve()}"
        )
        return [
            _check(
                "workspace",
                "WARN",
                where,
                "Name one with -w, or run 'hmp workspace init <workspace>'",
            )
        ]
    checks = [
        _check("workspace", "OK", f"{ws}"),
        _path_check("data_dir", ws / "data"),
    ]
    project_roots = []
    projects_dir = ws / PROJECTS_DIRNAME
    standalone = not projects_dir.is_dir() and (catalog_path_for(ws)).is_file()
    if not standalone:
        # A standalone project owns its index at the root and has no
        # ``projects/`` tree, so reporting one as missing would be noise.
        checks.append(_path_check("projects_dir", projects_dir))
    checks.append(_data_cache_check(ws / "data"))
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
            _check(
                "results:diagnostics",
                "KO",
                f"storage diagnostics import failed: {exc}",
                "Reinstall hydromodpy",
            )
        ]
    return [
        diagnostic.to_check()
        for diagnostic in diagnose_result_storage(
            ws,
            catalog_path=catalog_path,
            runs_dir=runs_dir,
        )
    ]


def probe_toml_workspace(toml_path: Path) -> list[dict]:
    """Check the workspace a TOML file resolves to: where it comes from, and its folders."""
    from hydromodpy.core.workspace.config import WorkspaceConfig
    from hydromodpy.core.workspace.exceptions import WorkspaceError

    try:
        from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
        from hydromodpy.core.state.result_dirs import resolve_project_root
        from hydromodpy.core.toml_io.loader import load_toml_with_base_config
        from hydromodpy.core.toml_io.paths import resolve_declared_path

        raw = load_toml_with_base_config(toml_path, root=ROOT_CONFIG)
        # Every relative path of a project is read from its root, the folder
        # that holds project.toml, and the loader sets project_root to it.
        base_dir = resolve_project_root(toml_path.parent)
        workspace_section = dict(raw.get("workspace", {}))
        for key in ("root", "data_dir"):
            if key in workspace_section and workspace_section[key] is not None:
                workspace_section[key] = str(
                    resolve_declared_path(workspace_section[key], base_dir=base_dir)
                )
        workspace_section["project_root"] = str(base_dir)
        cfg = WorkspaceConfig.model_validate(workspace_section)
    except WorkspaceError as exc:
        return [_check("workspace", "KO", f"resolution failed for {toml_path}", str(exc))]
    except Exception as exc:  # noqa: BLE001 - this check informs, the findings refuse
        return [_check("workspace", "KO", f"config load failed: {exc}")]

    checks = [
        _check("workspace", "OK", f"resolved via {cfg.resolution_source}"),
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


def _data_cache_check(data_dir: Path) -> dict:
    """Report on the sidecars of ``data/`` and on a database of HydroModPy 2.0.0 left there.

    It reads and never repairs: the database is removed by ``hmp workspace clean
    --data-cache``, and a sidecar that does not read is named so its file can go.
    """
    from hydromodpy.core.exceptions import DataCacheError
    from hydromodpy.data.provenance.sidecars import scan

    if not data_dir.is_dir():
        return _check(
            "data_cache", "WARN", f"{data_dir} (missing)", "Created lazily when first used"
        )
    try:
        report = scan(data_dir)
    except DataCacheError as exc:
        return _check(
            "data_cache",
            "WARN",
            str(exc),
            "hmp workspace clean --data-cache removes it. The doctor does not.",
        )
    notes = report.lines()
    detail = f"{len(report.rows)} row(s), {len(report.user_files)} user file(s)"
    if notes:
        return _check(
            "data_cache", "WARN", f"{detail}. {notes[0]}", f"{len(notes)} sidecar(s) are no row"
        )
    return _check("data_cache", "OK", detail)


def _path_check(name: str, path: Path, *, required: bool = True) -> dict:
    if path.exists():
        status = "OK"
        detail = f"{path}"
        hint = None
    else:
        status = "WARN"
        detail = f"{path} (missing)"
        hint = "Created lazily when first used" if not required else None
    return _check(name, status, detail, hint)


def _cross_catalog_checks(workspace: Path | None) -> list[dict]:
    """Compare the sealed runs on disk with the index of each project.

    Disk is the truth: a sealed run missing from its index, or an index row
    whose directory is gone, means the index is behind. Both are fixed by
    ``hmp catalog reindex``.
    """
    if workspace is None:
        return [
            _check("cross_catalog:workspace", "WARN", "no workspace resolved", "Name one with -w")
        ]

    import duckdb

    from hydromodpy.core.exceptions import CatalogUnreadableError
    from hydromodpy.core.state.layout import catalog_path_for, project_roots_under
    from hydromodpy.results.catalog.federation import sealed_run_dirs
    from hydromodpy.results.catalog.index_file import open_index

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
            conn = open_index(project_root)
        except CatalogUnreadableError:
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
        _check(
            "cross_catalog:runs_vs_index",
            "OK" if missing_from_index == 0 else "WARN",
            f"{n_sealed} sealed run(s) on disk, {missing_from_index} missing from an index",
            hint,
        ),
        _check(
            "cross_catalog:index_vs_runs",
            "OK" if missing_on_disk == 0 else "WARN",
            f"{missing_on_disk} index row(s) whose directory is gone",
            hint,
        ),
    ]


def _lifecycle_checks(workspace: Path | None) -> list[dict]:
    """Count stale attempts, abandoned or orphan sessions and tmp files, from the disk."""
    if workspace is None:
        return [_check("lifecycle:workspace", "WARN", "no workspace resolved", "Name one with -w")]

    from hydromodpy.core.state.layout import project_roots_under
    from hydromodpy.results.catalog.liveness import (
        ABANDONED_SESSION_MINUTES,
        abandoned_calibration_session_count,
        orphan_calibration_session_count,
        stale_running_sim_ids,
    )
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
            "hint": "Run 'hmp catalog gc -y' in the project to mark them aborted",
        },
        {
            "name": "lifecycle:abandoned_calibration_sessions",
            "status": "OK" if abandoned_sessions == 0 else "WARN",
            "detail": (
                f"{abandoned_sessions} calibration session(s) still running after "
                f"{ABANDONED_SESSION_MINUTES // 60} h with no outcome"
            ),
            "hint": "Run 'hmp catalog gc -y' in the project to close them as aborted",
        },
        _check(
            "lifecycle:orphan_calibration_sessions",
            "OK" if orphan_sessions == 0 else "WARN",
            f"{orphan_sessions} calibration session(s) name a best run that is gone",
            "Restore the run from trash/ (hmp catalog restore) or delete the session",
        ),
        _check(
            "lifecycle:tmp_files",
            "OK" if tmp_files == 0 else "WARN",
            f"{tmp_files} stale tmp-* file(s) on disk",
            "Run 'hmp catalog gc -y' in the project to clean them up",
        ),
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
            _check(
                "prt:mf6", "KO", "not cached, not on PATH", "Run 'hmp install-binaries --mf6-prt'"
            )
        ]

    banner, version = _mf6_version(executable)
    checks = [_check("prt:mf6", "OK", str(executable))]

    if version is None:
        checks.append(
            _check(
                "prt:mf6_version",
                "WARN",
                f"unreadable version banner: {banner or 'empty'}",
                f"PRT needs MODFLOW {minimum} or newer",
            )
        )
    else:
        readable = ".".join(str(part) for part in version)
        supported = version >= _PRT_MIN_MF6_VERSION
        checks.append(
            _check(
                "prt:mf6_version",
                "OK" if supported else "KO",
                f"{readable} (PRT needs >= {minimum})",
                None if supported else "Run 'hmp install-binaries --mf6-prt --upgrade'",
            )
        )

    try:
        import flopy

        has_prt = hasattr(flopy.mf6, "ModflowPrt")
    except ImportError as exc:
        checks.append(_check("prt:flopy", "KO", f"{exc}", "pip install -e . (re-install editable)"))
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
