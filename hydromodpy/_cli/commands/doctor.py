"""``hmp doctor`` — diagnose the local environment."""

from __future__ import annotations

import argparse
import importlib
import os
import platform
import shutil
import sys
from pathlib import Path


NAME = "doctor"
HELP = "Diagnose the local environment (Python, deps, solvers, workspace)"


_CORE_DEPS = (
    "numpy", "pandas", "scipy", "duckdb", "zarr", "pyproj",
    "rasterio", "shapely", "xarray", "flopy", "pydantic",
    "pint", "matplotlib",
)

_OPTIONAL_DEPS = ("gmsh", "whitebox_workflows", "geopandas", "pyvista")

_SOLVER_BINARIES = ("mf2005", "mfnwt", "mf6", "mp7")


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("--workspace", default=None,
                        help="Probe this workspace (default: ~/hydromodpy/)")
    parser.add_argument("--json", action="store_true",
                        help="Emit a JSON report")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    report = _build_report(args.workspace)

    if args.json:
        import json as _json
        print(_json.dumps(report, indent=2, default=str))
    else:
        _print_report(report)

    if any(entry.get("status") == "KO" for entry in report["checks"]):
        sys.exit(1)


def _build_report(workspace_arg: str | None) -> dict:
    from hydromodpy.core.version import __version__ as hmp_version

    checks: list[dict] = []

    python_ok = sys.version_info >= (3, 11)
    checks.append({
        "name": "python",
        "status": "OK" if python_ok else "KO",
        "detail": f"{platform.python_version()} ({sys.executable})",
        "hint": None if python_ok else "HydroModPy requires Python >= 3.11",
    })

    checks.append({
        "name": "platform",
        "status": "OK",
        "detail": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "hint": None,
    })

    checks.append({
        "name": "hydromodpy",
        "status": "OK",
        "detail": f"version {hmp_version}",
        "hint": None,
    })

    for dep in _CORE_DEPS:
        try:
            mod = importlib.import_module(dep)
            version = getattr(mod, "__version__", "unknown")
            checks.append({
                "name": f"dep:{dep}",
                "status": "OK",
                "detail": f"{version}",
                "hint": None,
            })
        except ImportError as exc:
            checks.append({
                "name": f"dep:{dep}",
                "status": "KO",
                "detail": f"{exc}",
                "hint": "pip install -e . (re-install editable)",
            })

    for dep in _OPTIONAL_DEPS:
        try:
            mod = importlib.import_module(dep)
            version = getattr(mod, "__version__", "unknown")
            checks.append({
                "name": f"opt:{dep}",
                "status": "OK",
                "detail": f"{version}",
                "hint": None,
            })
        except ImportError:
            checks.append({
                "name": f"opt:{dep}",
                "status": "WARN",
                "detail": "not installed",
                "hint": "optional",
            })

    try:
        import duckdb  # noqa: F401
        checks.append({
            "name": "duckdb:open",
            "status": "OK",
            "detail": "opens in-memory database",
            "hint": None,
        })
    except Exception as exc:
        checks.append({
            "name": "duckdb:open",
            "status": "KO",
            "detail": str(exc),
            "hint": "Reinstall duckdb",
        })

    for binary in _SOLVER_BINARIES:
        location = shutil.which(binary)
        if location:
            checks.append({
                "name": f"solver:{binary}",
                "status": "OK",
                "detail": location,
                "hint": None,
            })
        else:
            checks.append({
                "name": f"solver:{binary}",
                "status": "WARN",
                "detail": "not on PATH",
                "hint": "Install via conda or copy into ~/hydromodpy/bin/",
            })

    workspace = _probe_workspace(workspace_arg)
    checks.append(workspace)

    return {
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()}",
        "hydromodpy": hmp_version,
        "checks": checks,
    }


def _probe_workspace(workspace_arg: str | None) -> dict:
    try:
        from hydromodpy.data.scaffold import DEFAULT_ROOT
    except Exception as exc:  # pragma: no cover
        return {
            "name": "workspace",
            "status": "KO",
            "detail": f"scaffold import failed: {exc}",
            "hint": "Reinstall hydromodpy",
        }
    ws = Path(workspace_arg).expanduser().resolve() if workspace_arg else Path(DEFAULT_ROOT).expanduser()
    if not ws.exists():
        return {
            "name": "workspace",
            "status": "WARN",
            "detail": f"{ws} does not exist",
            "hint": "Run 'hmp init' to create a workspace",
        }
    db = ws / "hydromodpy.duckdb"
    cache = ws / "data" / "cache.duckdb"
    detail = f"{ws} (db={db.exists()}, cache={cache.exists()})"
    return {
        "name": "workspace",
        "status": "OK",
        "detail": detail,
        "hint": None,
    }


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
