"""What this machine runs: Python, HydroModPy, the packages and the solver executables.

:func:`doctor_report` is quick by design. It starts no solver and imports only the
packages it lists, so a script can call it at import time.

The checks of ``hmp doctor`` sit below it. Each one gives rows of the report, a
dict with a ``name``, a ``status`` (``OK``, ``WARN`` or ``KO``), what was seen
(``detail``) and what to do (``hint``). The command prints them. The checks
import what they read inside their body, so this module stays cheap to import.
"""

from __future__ import annotations

import importlib
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from hydromodpy.core.version import __version__

if TYPE_CHECKING:
    from hydromodpy.core.diagnostic import Diagnostic

REQUIRED_PACKAGES: Final[tuple[str, ...]] = (
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
"""The packages HydroModPy cannot run without."""

OPTIONAL_PACKAGES: Final[tuple[str, ...]] = ("gmsh", "whitebox_workflows", "geopandas")
"""The packages a feature needs: a mesh engine, a terrain engine, a reader."""

PACKAGES: Final[tuple[str, ...]] = REQUIRED_PACKAGES + OPTIONAL_PACKAGES
"""The packages the report names, each with its version."""

SOLVERS: Final[tuple[str, ...]] = ("mf2005", "mfnwt", "mf6", "mp6", "mp7", "mt3dusgs")
"""The executables the report looks for on the ``PATH``."""

SOLVER_BINARIES: Final[tuple[str, ...]] = tuple(name for name in SOLVERS if name != "mf2005")
"""The executables ``hmp install-binaries`` fetches, so the ones ``hmp doctor`` can say how to install."""

PRT_MIN_MF6_VERSION: Final[tuple[int, int, int]] = (6, 5, 0)
"""The PRT model shipped with MODFLOW 6.5.0. Older executables run, but reject a PRT name file."""


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """The state of the machine: versions, packages and solver executables."""

    python: str
    """Version of the Python interpreter."""
    hydromodpy: str
    """Version of HydroModPy."""
    solvers: dict[str, str | None]
    """Each solver executable and the path it was found at, ``None`` when missing."""
    optional: dict[str, str | None]
    """Each package of :data:`PACKAGES` and its version, ``None`` when it does not import."""

    def to_dict(self) -> dict[str, Any]:
        """Return the report as JSON, with ``python``, ``hydromodpy``, ``solvers`` and ``optional``."""
        return {
            "python": self.python,
            "hydromodpy": self.hydromodpy,
            "solvers": dict(self.solvers),
            "optional": dict(self.optional),
        }


def doctor_report() -> DoctorReport:
    """Return what this machine runs. No solver is started."""
    versions: dict[str, str | None] = {}
    for name in PACKAGES:
        try:
            module = importlib.import_module(name)
            versions[name] = getattr(module, "__version__", "?")
        except Exception:  # noqa: BLE001 - a package that fails to import is reported as missing
            versions[name] = None
    return DoctorReport(
        python=platform.python_version(),
        hydromodpy=__version__,
        solvers={exe: shutil.which(exe) for exe in SOLVERS},
        optional=versions,
    )


def check_row(name: str, status: str, detail: str, hint: str | None = None) -> dict:
    """One row of the report: a name, OK, WARN or KO, what was seen, and what to do."""
    return {"name": name, "status": status, "detail": detail, "hint": hint}


def build_report(machine: dict, workspace: Path | None, workspace_arg: str | None) -> dict:
    """Return the report of ``hmp doctor``: the machine, the packages, the solvers, the workspace.

    *machine* is ``doctor_report().to_dict()``, the answer of the verb ``doctor``.
    """
    hmp_version = machine["hydromodpy"]
    checks: list[dict] = []

    python_ok = sys.version_info >= (3, 11)
    checks.append(
        check_row(
            "python",
            "OK" if python_ok else "KO",
            f"{machine['python']} ({sys.executable})",
            None if python_ok else "HydroModPy requires Python >= 3.11",
        )
    )

    checks.append(
        check_row(
            "platform", "OK", f"{platform.system()} {platform.release()} ({platform.machine()})"
        )
    )

    checks.append(check_row("hydromodpy", "OK", f"version {hmp_version}"))

    for dep in REQUIRED_PACKAGES:
        try:
            mod = importlib.import_module(dep)
            version = getattr(mod, "__version__", "unknown")
            checks.append(check_row(f"dep:{dep}", "OK", f"{version}"))
        except ImportError as exc:
            checks.append(
                check_row(f"dep:{dep}", "KO", f"{exc}", "pip install -e . (re-install editable)")
            )

    for dep in OPTIONAL_PACKAGES:
        try:
            mod = importlib.import_module(dep)
            version = getattr(mod, "__version__", "unknown")
            checks.append(check_row(f"opt:{dep}", "OK", f"{version}"))
        except ImportError:
            checks.append(check_row(f"opt:{dep}", "WARN", "not installed", "optional"))

    try:
        import duckdb  # noqa: F401

        checks.append(check_row("duckdb:open", "OK", "opens in-memory database"))
    except Exception as exc:
        checks.append(check_row("duckdb:open", "KO", str(exc), "Reinstall duckdb"))

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
            check_row(
                "solver:bin_path",
                "KO",
                f"bin path resolution failed: {exc}",
                "Reinstall hydromodpy",
            )
        )
    else:
        checks.append(check_row("solver:bin_path", "OK", str(effective_bin)))
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

    for binary in SOLVER_BINARIES:
        located = None
        if effective_bin is not None:
            try:
                located = locate_solver_binary(effective_bin, binary)
            except Exception:
                located = None
        path_hit = shutil.which(binary)
        if located:
            checks.append(check_row(f"solver:{binary}", "OK", str(located)))
        elif path_hit:
            checks.append(check_row(f"solver:{binary}", "OK", f"{path_hit} (from PATH)"))
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

    for entry in probe_workspace(workspace, workspace_arg):
        checks.append(entry)

    return {
        "python": machine["python"],
        "platform": f"{platform.system()} {platform.release()}",
        "hydromodpy": hmp_version,
        "checks": checks,
    }


def probe_workspace(ws: Path | None, workspace_arg: str | None) -> list[dict]:
    """Report on the workspace *ws* and on the storage of each project it holds."""
    try:
        from hydromodpy.core.state.layout import PROJECTS_DIRNAME, catalog_path_for
    except Exception as exc:  # pragma: no cover
        return [
            check_row("workspace", "KO", f"workspace import failed: {exc}", "Reinstall hydromodpy")
        ]

    if ws is None:
        where = (
            f"{Path(workspace_arg).expanduser().resolve()} is not a workspace"
            if workspace_arg
            else f"no workspace at or above {Path.cwd().resolve()}"
        )
        return [
            check_row(
                "workspace",
                "WARN",
                where,
                "Name one with -w, or run 'hmp workspace init <workspace>'",
            )
        ]
    checks = [
        check_row("workspace", "OK", f"{ws}"),
        path_check("data_dir", ws / "data"),
    ]
    project_roots = []
    projects_dir = ws / PROJECTS_DIRNAME
    standalone = not projects_dir.is_dir() and (catalog_path_for(ws)).is_file()
    if not standalone:
        # A standalone project owns its index at the root and has no
        # ``projects/`` tree, so reporting one as missing would be noise.
        checks.append(path_check("projects_dir", projects_dir))
    checks.append(data_cache_check(ws / "data"))
    if projects_dir.is_dir():
        project_roots.extend(p for p in sorted(projects_dir.iterdir()) if p.is_dir())
    elif standalone:
        project_roots.append(ws)
    for project_root in project_roots:
        checks.extend(probe_result_storage(project_root))
    return checks


def probe_result_storage(
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
            check_row(
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
        return [check_row("workspace", "KO", f"resolution failed for {toml_path}", str(exc))]
    except Exception as exc:  # noqa: BLE001 - this check informs, the findings refuse
        return [check_row("workspace", "KO", f"config load failed: {exc}")]

    checks = [
        check_row("workspace", "OK", f"resolved via {cfg.resolution_source}"),
        path_check("workspace_root", cfg.root),
        path_check("catalog_path", cfg.catalog_path),
        path_check("data_dir", cfg.data_dir),
        path_check("runs_dir", cfg.runs_dir),
    ]
    checks.extend(
        probe_result_storage(
            cfg.project_root,
            catalog_path=cfg.catalog_path,
            runs_dir=cfg.runs_dir,
        )
    )
    return checks


def data_cache_check(data_dir: Path) -> dict:
    """Report on the sidecars of ``data/`` and on a database of HydroModPy 2.0.0 left there.

    It reads and never repairs: the database is removed by ``hmp workspace clean
    --data-cache``, and a sidecar that does not read is named so its file can go.
    """
    from hydromodpy.core.exceptions import DataCacheError
    from hydromodpy.data.provenance.sidecars import scan

    if not data_dir.is_dir():
        return check_row(
            "data_cache", "WARN", f"{data_dir} (missing)", "Created lazily when first used"
        )
    try:
        report = scan(data_dir)
    except DataCacheError as exc:
        return check_row(
            "data_cache",
            "WARN",
            str(exc),
            "hmp workspace clean --data-cache removes it. The doctor does not.",
        )
    notes = report.lines()
    detail = f"{len(report.rows)} row(s), {len(report.user_files)} user file(s)"
    if notes:
        return check_row(
            "data_cache", "WARN", f"{detail}. {notes[0]}", f"{len(notes)} sidecar(s) are no row"
        )
    return check_row("data_cache", "OK", detail)


def path_check(name: str, path: Path, *, required: bool = True) -> dict:
    if path.exists():
        status = "OK"
        detail = f"{path}"
        hint = None
    else:
        status = "WARN"
        detail = f"{path} (missing)"
        hint = "Created lazily when first used" if not required else None
    return check_row(name, status, detail, hint)


def cross_catalog_checks(workspace: Path | None) -> list[dict]:
    """Compare the sealed runs on disk with the index of each project.

    Disk is the truth: a sealed run missing from its index, or an index row
    whose directory is gone, means the index is behind. Both are fixed by
    ``hmp catalog reindex``.
    """
    if workspace is None:
        return [
            check_row(
                "cross_catalog:workspace", "WARN", "no workspace resolved", "Name one with -w"
            )
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
        check_row(
            "cross_catalog:runs_vs_index",
            "OK" if missing_from_index == 0 else "WARN",
            f"{n_sealed} sealed run(s) on disk, {missing_from_index} missing from an index",
            hint,
        ),
        check_row(
            "cross_catalog:index_vs_runs",
            "OK" if missing_on_disk == 0 else "WARN",
            f"{missing_on_disk} index row(s) whose directory is gone",
            hint,
        ),
    ]


def lifecycle_checks(workspace: Path | None) -> list[dict]:
    """Count stale attempts, abandoned or orphan sessions and tmp files, from the disk."""
    if workspace is None:
        return [
            check_row("lifecycle:workspace", "WARN", "no workspace resolved", "Name one with -w")
        ]

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
        check_row(
            "lifecycle:orphan_calibration_sessions",
            "OK" if orphan_sessions == 0 else "WARN",
            f"{orphan_sessions} calibration session(s) name a best run that is gone",
            "Restore the run from trash/ (hmp catalog restore) or delete the session",
        ),
        check_row(
            "lifecycle:tmp_files",
            "OK" if tmp_files == 0 else "WARN",
            f"{tmp_files} stale tmp-* file(s) on disk",
            "Run 'hmp catalog gc -y' in the project to clean them up",
        ),
    ]


def locate_mf6() -> Path | None:
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


def mf6_version(executable: Path) -> tuple[str, tuple[int, ...] | None]:
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


def prt_checks() -> list[dict]:
    """Report whether the local MODFLOW 6 build can run a PRT model."""
    minimum = ".".join(str(part) for part in PRT_MIN_MF6_VERSION)

    executable = locate_mf6()
    if executable is None:
        return [
            check_row(
                "prt:mf6", "KO", "not cached, not on PATH", "Run 'hmp install-binaries --mf6-prt'"
            )
        ]

    banner, version = mf6_version(executable)
    checks = [check_row("prt:mf6", "OK", str(executable))]

    if version is None:
        checks.append(
            check_row(
                "prt:mf6_version",
                "WARN",
                f"unreadable version banner: {banner or 'empty'}",
                f"PRT needs MODFLOW {minimum} or newer",
            )
        )
    else:
        readable = ".".join(str(part) for part in version)
        supported = version >= PRT_MIN_MF6_VERSION
        checks.append(
            check_row(
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
        checks.append(
            check_row("prt:flopy", "KO", f"{exc}", "pip install -e . (re-install editable)")
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


def findings_of(file: Path) -> list[Diagnostic]:
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


def refusal_in(held: Sequence[Diagnostic]) -> Exception | None:
    """Return the refusal made of the ``retired_key`` diagnostics of *held*, else ``None``."""
    from hydromodpy.core.exceptions import ConfigValidationError

    retired = [item for item in held if item.code == "retired_key"]
    if not retired:
        return None
    return ConfigValidationError("\n".join(item.detail for item in retired), diagnostics=retired)


def refusal_of(file: Path) -> Exception | None:
    """Return what the check says of *file* when it refuses a retired key, else ``None``.

    A partial file is refused for reasons that are not a retired key, and only a
    key the loader no longer accepts is the doctor's business.
    """
    return refusal_in(findings_of(file))
