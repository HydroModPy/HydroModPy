"""``hmp doctor`` - diagnose the local environment."""

from __future__ import annotations

import argparse
import importlib
import platform
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

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

_OPTIONAL_DEPS = ("gmsh", "whitebox_workflows", "geopandas", "pyvista")

_SOLVER_BINARIES = ("mfnwt", "mf6", "mp6", "mp7", "mt3dusgs")

_STALE_HEARTBEAT_MINUTES = 10


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "--workspace", default=None, help="Probe this workspace (default: ~/hydromodpy/)"
    )
    parser.add_argument("--toml", default=None, help="Resolve the workspace from a project TOML")
    parser.add_argument("--json", action="store_true", help="Emit a JSON report")
    parser.add_argument(
        "--cross-catalog",
        action="store_true",
        help="Cross-check the global index against per-project catalogs",
    )
    parser.add_argument(
        "--lifecycle",
        action="store_true",
        help="Surface lifecycle issues (orphan sims, tmp parquet, stale running rows)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    report = _build_report(args.workspace, toml=args.toml)

    if getattr(args, "cross_catalog", False):
        report["checks"].extend(_cross_catalog_checks(args.workspace))
    if getattr(args, "lifecycle", False):
        report["checks"].extend(_lifecycle_checks(args.workspace))

    if args.json:
        import json as _json

        print(_json.dumps(report, indent=2, default=str))
    else:
        _print_report(report)

    if any(entry.get("status") == "KO" for entry in report["checks"]):
        sys.exit(1)


def _build_report(workspace_arg: str | None, *, toml: str | None = None) -> dict:
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

    for entry in _probe_workspace(workspace_arg, toml=toml):
        checks.append(entry)

    return {
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()}",
        "hydromodpy": hmp_version,
        "checks": checks,
    }


def _probe_workspace(workspace_arg: str | None, *, toml: str | None) -> list[dict]:
    try:
        from hydromodpy.core.state.paths import CATALOG_FILENAME
        from hydromodpy.core.workspace.config import WorkspaceConfig
        from hydromodpy.core.workspace.exceptions import WorkspaceError
        from hydromodpy.data.scaffold import DEFAULT_ROOT
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

    ws = (
        Path(workspace_arg).expanduser().resolve()
        if workspace_arg
        else Path(DEFAULT_ROOT).expanduser()
    )
    if not ws.exists():
        return [
            {
                "name": "workspace",
                "status": "WARN",
                "detail": f"{ws} does not exist",
                "hint": "Run 'hmp init <workspace>' to scaffold one",
            }
        ]
    cache = ws / "data" / "cache.duckdb"
    checks = [
        {
            "name": "workspace",
            "status": "OK",
            "detail": f"{ws}",
            "hint": None,
        },
        _path_check("data_dir", ws / "data"),
        _path_check("projects_dir", ws / "projects"),
        _path_check("data_cache", cache, required=False),
    ]
    project_roots = []
    projects_dir = ws / "projects"
    if projects_dir.is_dir():
        project_roots.extend(p for p in sorted(projects_dir.iterdir()) if p.is_dir())
    elif (ws / CATALOG_FILENAME).is_file():
        project_roots.append(ws)
    for project_root in project_roots:
        checks.extend(_probe_result_storage(project_root))
    return checks


def _probe_result_storage(
    ws: Path,
    *,
    catalog_path: Path | None = None,
    simulations_dir: Path | None = None,
) -> list[dict]:
    """Report on the catalog/Zarr/Parquet storage layout."""
    try:
        from hydromodpy.results.storage_diagnostics import diagnose_result_storage
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
            simulations_dir=simulations_dir,
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
        from hydromodpy.core.toml_io.loader import load_toml_with_base_config
        from hydromodpy.core.toml_io.paths import resolve_declared_path

        raw = load_toml_with_base_config(toml_path)
        base_dir = toml_path.parent
        workspace_section = dict(raw.get("workspace", {}))
        for key in (
            "project_root",
            "root",
            "catalog_path",
            "data_dir",
            "simulations_dir",
            "output_root",
        ):
            if key in workspace_section and workspace_section[key] is not None:
                workspace_section[key] = str(
                    resolve_declared_path(workspace_section[key], base_dir=base_dir)
                )
        workspace_section.setdefault("project_root", str(base_dir))
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
        _path_check("simulations_dir", cfg.simulations_dir),
    ]
    checks.extend(
        _probe_result_storage(
            cfg.project_root,
            catalog_path=cfg.catalog_path,
            simulations_dir=cfg.simulations_dir,
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


def _iter_project_catalogs(workspace: Path) -> list[Path]:
    from hydromodpy.core.state.paths import CATALOG_FILENAME

    catalogs: list[Path] = []
    if (workspace / CATALOG_FILENAME).is_file():
        catalogs.append(workspace / CATALOG_FILENAME)
    projects_dir = workspace / "projects"
    if projects_dir.is_dir():
        for entry in sorted(projects_dir.iterdir()):
            cat = entry / CATALOG_FILENAME
            if cat.is_file():
                catalogs.append(cat)
    return catalogs


def _resolve_doctor_workspace(workspace_arg: str | None) -> Path | None:
    try:
        from hydromodpy.data.scaffold import DEFAULT_ROOT
    except Exception:
        return None
    if workspace_arg is not None:
        candidate = Path(workspace_arg).expanduser().resolve()
    else:
        candidate = Path(DEFAULT_ROOT).expanduser()
    return candidate if candidate.is_dir() else None


def _cross_catalog_checks(workspace_arg: str | None) -> list[dict]:
    workspace = _resolve_doctor_workspace(workspace_arg)
    if workspace is None:
        return [
            {
                "name": "cross_catalog:workspace",
                "status": "WARN",
                "detail": "no workspace resolved",
                "hint": "Pass --workspace <path>",
            }
        ]

    try:
        import duckdb

        from hydromodpy.core.state.global_index import GlobalIndex
        from hydromodpy.core.state.paths import resolve_workspace as _resolve_uri
    except Exception as exc:  # pragma: no cover - defensive
        return [
            {
                "name": "cross_catalog:imports",
                "status": "KO",
                "detail": f"{exc}",
                "hint": "Reinstall hydromodpy",
            }
        ]

    project_catalogs = _iter_project_catalogs(workspace)
    project_sim_ids: set[str] = set()
    for catalog_path in project_catalogs:
        try:
            conn = duckdb.connect(str(catalog_path), read_only=True)
        except duckdb.Error:
            continue
        try:
            rows = conn.execute("SELECT sim_id FROM simulations").fetchall()
            project_sim_ids.update(str(r[0]) for r in rows)
        except duckdb.Error:
            pass
        finally:
            conn.close()

    index_sim_ids: set[str] = set()
    try:
        with GlobalIndex() as gi:
            df = gi.find()
            if df is not None and not df.empty and "sim_id" in df.columns:
                index_sim_ids = {str(v) for v in df["sim_id"].tolist()}
            try:
                workspace_ids_local = {
                    record.workspace_id
                    for record in gi.list_workspaces()
                    if _resolve_uri(record.workspace_uri) == workspace
                }
            except Exception:
                workspace_ids_local = set()
    except Exception as exc:
        return [
            {
                "name": "cross_catalog:index_open",
                "status": "KO",
                "detail": f"{exc}",
                "hint": "Re-create the global index via hmp index search/forget/prune",
            }
        ]

    checks: list[dict] = []
    only_in_projects = project_sim_ids - index_sim_ids
    only_in_index = index_sim_ids - project_sim_ids

    checks.append(
        {
            "name": "cross_catalog:workspace_registered",
            "status": "OK" if workspace_ids_local else "WARN",
            "detail": (
                f"{len(workspace_ids_local)} registration(s) match {workspace}"
                if workspace_ids_local
                else "workspace not registered in the global index"
            ),
            "hint": "Register via the manage verb if needed",
        }
    )
    checks.append(
        {
            "name": "cross_catalog:projects_vs_index",
            "status": "OK" if not only_in_projects else "WARN",
            "detail": (
                f"{len(project_sim_ids)} sim(s) in projects, "
                f"{len(only_in_projects)} missing from index"
            ),
            "hint": "Refresh the index federation (open and close a GlobalIndex)",
        }
    )
    checks.append(
        {
            "name": "cross_catalog:index_vs_projects",
            "status": "OK" if not only_in_index else "WARN",
            "detail": (
                f"{len(index_sim_ids)} sim(s) in index, {len(only_in_index)} missing from projects"
            ),
            "hint": "Run 'hmp index prune' to drop stale registrations",
        }
    )
    return checks


def _lifecycle_checks(workspace_arg: str | None) -> list[dict]:
    workspace = _resolve_doctor_workspace(workspace_arg)
    if workspace is None:
        return [
            {
                "name": "lifecycle:workspace",
                "status": "WARN",
                "detail": "no workspace resolved",
                "hint": "Pass --workspace <path>",
            }
        ]

    try:
        import duckdb
    except Exception as exc:
        return [
            {
                "name": "lifecycle:duckdb",
                "status": "KO",
                "detail": f"{exc}",
                "hint": "Reinstall duckdb",
            }
        ]

    project_catalogs = _iter_project_catalogs(workspace)
    cutoff = datetime.now(UTC) - timedelta(minutes=_STALE_HEARTBEAT_MINUTES)
    stale_running = 0
    orphan_sessions = 0
    for catalog_path in project_catalogs:
        try:
            conn = duckdb.connect(str(catalog_path), read_only=True)
        except duckdb.Error:
            continue
        try:
            stale = conn.execute(
                """
                SELECT COUNT(*)
                  FROM simulations s
                  JOIN statuses st ON s.status_id = st.id
                 WHERE st.code = 'running'
                   AND (s.last_heartbeat IS NULL OR s.last_heartbeat < ?)
                """,
                [cutoff],
            ).fetchone()
            stale_running += int(stale[0]) if stale else 0

            orphans = conn.execute(
                """
                SELECT COUNT(*)
                  FROM calibration_sessions cs
             LEFT JOIN simulations s ON s.sim_id = cs.best_sim_id
                 WHERE cs.best_sim_id IS NOT NULL AND s.sim_id IS NULL
                """,
            ).fetchone()
            orphan_sessions += int(orphans[0]) if orphans else 0
        except duckdb.Error:
            pass
        finally:
            conn.close()

    tmp_parquet = sum(1 for _ in workspace.rglob("*.tmp-*"))

    return [
        {
            "name": "lifecycle:stale_running_sims",
            "status": "OK" if stale_running == 0 else "WARN",
            "detail": f"{stale_running} sim(s) running >{_STALE_HEARTBEAT_MINUTES} min without heartbeat",
            "hint": "Run 'hmp gc --workspace <ws>' to mark them failed",
        },
        {
            "name": "lifecycle:orphan_calibration_sessions",
            "status": "OK" if orphan_sessions == 0 else "WARN",
            "detail": f"{orphan_sessions} calibration session(s) reference a missing best_sim_id",
            "hint": "Run 'hmp gc --workspace <ws>' to drop them",
        },
        {
            "name": "lifecycle:tmp_parquet",
            "status": "OK" if tmp_parquet == 0 else "WARN",
            "detail": f"{tmp_parquet} stale tmp-* artefact(s) on disk",
            "hint": "Run 'hmp gc --workspace <ws>' to clean them up",
        },
    ]


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
