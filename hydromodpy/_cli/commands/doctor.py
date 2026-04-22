"""``hmp doctor`` — diagnose the local environment."""

from __future__ import annotations

import argparse
import importlib
import platform
import shutil
import sys
from pathlib import Path

NAME = "doctor"
HELP = "Diagnose the local environment (Python, deps, solvers, workspace)"


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

_SOLVER_BINARIES = ("mf2005", "mfnwt", "mf6", "mp7")


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "--workspace", default=None, help="Probe this workspace (default: ~/hydromodpy/)"
    )
    parser.add_argument("--toml", default=None, help="Resolve the workspace from a project TOML")
    parser.add_argument("--json", action="store_true", help="Emit a JSON report")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    report = _build_report(args.workspace, toml=args.toml)

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

    for binary in _SOLVER_BINARIES:
        location = shutil.which(binary)
        if location:
            checks.append(
                {
                    "name": f"solver:{binary}",
                    "status": "OK",
                    "detail": location,
                    "hint": None,
                }
            )
        else:
            checks.append(
                {
                    "name": f"solver:{binary}",
                    "status": "WARN",
                    "detail": "not on PATH",
                    "hint": "Install via conda or copy into ~/hydromodpy/bin/",
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
    db = ws / "hydromodpy.duckdb"
    cache = ws / "data" / "cache.duckdb"
    sims = ws / "simulations"
    checks = [
        {
            "name": "workspace",
            "status": "OK",
            "detail": f"{ws}",
            "hint": None,
        },
        _path_check("catalog_path", db),
        _path_check("data_dir", ws / "data"),
        _path_check("simulations_dir", sims),
        _path_check("data_cache", cache, required=False),
    ]
    checks.extend(_probe_parquet_layout(ws))
    return checks


def _probe_parquet_layout(ws: Path) -> list[dict]:
    """Report on the per-sim Parquet directories and flag inconsistencies."""
    db = ws / "hydromodpy.duckdb"
    if not db.is_file():
        return []
    try:
        import duckdb as _duckdb
    except ImportError:
        return []
    try:
        conn = _duckdb.connect(str(db), read_only=True)
    except _duckdb.IOException as exc:
        return [
            {
                "name": "parquet:catalog",
                "status": "WARN",
                "detail": f"catalog busy: {exc}",
                "hint": "Close other HydroModPy sessions and retry",
            }
        ]
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='main' AND table_type='BASE TABLE'"
            ).fetchall()
        }
        registered = {
            str(r[0])
            for r in conn.execute("SELECT CAST(sim_id AS VARCHAR) FROM simulations").fetchall()
        }
    finally:
        conn.close()

    out: list[dict] = []
    legacy = {"timeseries", "budgets", "mass_balance"} & tables
    if legacy:
        out.append(
            {
                "name": "parquet:layout",
                "status": "WARN",
                "detail": f"legacy tables present: {', '.join(sorted(legacy))}",
                "hint": "Regenerate the workspace; legacy DuckDB tables are no longer supported.",
            }
        )
    sims_dir = ws / "simulations"
    if not sims_dir.is_dir():
        return out
    parquet_dirs = {p.name[: -len(".parquet")]: p for p in sims_dir.glob("*.parquet") if p.is_dir()}
    orphan = sorted(set(parquet_dirs) - registered)
    if orphan:
        out.append(
            {
                "name": "parquet:orphan_dirs",
                "status": "WARN",
                "detail": f"{len(orphan)} parquet dir(s) without a catalog row",
                "hint": f"first: {orphan[0]} (rm or re-register)",
            }
        )
    else:
        out.append(
            {
                "name": "parquet:layout",
                "status": "OK",
                "detail": f"{len(parquet_dirs)} per-sim Parquet dir(s)",
                "hint": None,
            }
        )
    return out


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
        from hydromodpy.core.config.path_resolution import resolve_declared_path
        from hydromodpy.core.config.toml_loader import load_toml_with_base_config

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
        cfg = WorkspaceConfig(**workspace_section)
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

    return [
        {
            "name": "workspace",
            "status": "OK",
            "detail": f"resolved via {cfg.resolution_source}",
            "hint": None,
        },
        _path_check("workspace_root", cfg.workspace_root),
        _path_check("catalog_path", cfg.catalog_path),
        _path_check("data_dir", cfg.data_dir),
        _path_check("simulations_dir", cfg.simulations_dir),
    ]


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
