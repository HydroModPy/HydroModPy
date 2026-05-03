"""Shared CLI helpers: exit codes, error formatting, workspace lookups."""

from __future__ import annotations

import os
import re
import sys
import tempfile
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Standardised exit codes (architecture_cible/10_ux_cli_api.md §5.1).
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_RUN_FAILED = 2
EXIT_NOT_FOUND = 3
EXIT_USER_ABORT = 4
EXIT_DATA_ERROR = 5
EXIT_SOLVER_ERROR = 6
EXIT_SIGINT = 130


# ---------------------------------------------------------------------------
# Workspace / project discovery
# ---------------------------------------------------------------------------


def find_project_root() -> Path:
    """Walk up from this file to find the directory containing ``tests/``."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "tests").is_dir():
            return parent
    return Path.cwd()


def find_workspace_root(project_dir: Path) -> Path:
    """Walk up from ``project_dir`` to find the shared data workspace."""
    start = project_dir.resolve()
    if start.name == "projects" and start.parent.is_dir():
        return start.parent
    for parent in [start] + list(start.parents):
        if parent.parent.name == "projects":
            return parent.parent.parent
        if (parent / "projects").is_dir() or (parent / "data").is_dir():
            return parent
    return start


def find_catalog_root(project_dir: Path) -> Path:
    """Walk up from ``project_dir`` to find a project-local catalog."""
    for parent in [project_dir] + list(project_dir.parents):
        if (parent / "hydromodpy.duckdb").exists():
            return parent
    return project_dir


def find_data_workspace(start: Path) -> Path | None:
    """Walk up from ``start`` to find a workspace containing ``*_custom/``."""
    for parent in [start] + list(start.parents):
        for child in parent.iterdir() if parent.is_dir() else []:
            if child.is_dir() and child.name.endswith("_custom"):
                return parent
    return None


def resolve_workspace(workspace_arg: str | None) -> Path:
    """Resolve the workspace root from an optional CLI argument."""
    from hydromodpy.data.scaffold import DEFAULT_ROOT

    root = Path(workspace_arg).expanduser().resolve() if workspace_arg else DEFAULT_ROOT
    if not root.is_dir():
        print(
            f"Workspace {root} does not exist. Run 'hmp init' first.",
            file=sys.stderr,
        )
        sys.exit(EXIT_NOT_FOUND)
    return root


def resolve_sim_id(catalog, sim_id_or_prefix: str) -> str:
    """Resolve a simulation reference to its full ``sim_id``.

    Delegates to :meth:`SimulationCatalog.resolve` and exits the CLI with a
    friendly message when the reference is ambiguous or missing.
    """
    from hydromodpy.results.catalog import (
        AmbiguousReferenceError,
        SimulationNotFoundError,
    )

    try:
        return catalog.resolve(sim_id_or_prefix)
    except AmbiguousReferenceError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except SimulationNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)


# ---------------------------------------------------------------------------
# Auto-scan workspace for drag-and-drop custom folders
# ---------------------------------------------------------------------------


def auto_scan_workspace(config_path: Path) -> None:
    """Best-effort scan of drag-and-drop custom folders before a run."""
    try:
        project_dir = config_path.parent.resolve()
        ws = find_data_workspace(project_dir)
        if ws is None:
            return
        from hydromodpy.data.auto_scan import scan_custom

        report = scan_custom(ws)
        if report.n_changed or report.errors:
            print(
                f"[auto_scan] {len(report.added)} added, "
                f"{len(report.updated)} updated, "
                f"{len(report.errors)} error(s) in {ws}",
                file=sys.stderr,
            )
            for path, msg in report.errors[:5]:
                print(f"[auto_scan]   ! {path}: {msg}", file=sys.stderr)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[auto_scan] skipped ({type(exc).__name__}: {exc})", file=sys.stderr)


# ---------------------------------------------------------------------------
# Pytest scratch environment helpers
# ---------------------------------------------------------------------------


def resolve_test_scratch_root() -> Path:
    """Return the shared repository-external scratch root for test runs."""
    override = os.environ.get("HYDROMODPY_TEST_SCRATCH_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return (Path(tempfile.gettempdir()) / "hydromodpy_tests").resolve()


def resolve_test_session_scratch_root(scratch_root: Path) -> Path:
    """Return the pytest scratch root for this CLI-launched test process tree."""
    override = os.environ.get("HYDROMODPY_TEST_SESSION_SCRATCH_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return (scratch_root / "sessions" / f"cli_{os.getpid()}_{uuid.uuid4().hex[:12]}").resolve()


def pytest_addopts_declares_basetemp(pytest_addopts: str) -> bool:
    """Return ``True`` when ``PYTEST_ADDOPTS`` already declares ``--basetemp``."""
    return re.search(r"(^|\\s)--basetemp(?:=|\\s|$)", str(pytest_addopts)) is not None


def build_pytest_runtime_env() -> tuple[Path, dict[str, str]]:
    """Prepare one external scratch root for pytest internals and subprocesses."""
    scratch_root = resolve_test_scratch_root()
    session_root = resolve_test_session_scratch_root(scratch_root)
    tmp_root = session_root / "tmp"
    pytest_root = session_root / "pytest"
    basetemp_root = pytest_root / f"cli_{os.getpid()}"
    for path in (scratch_root, session_root, tmp_root, pytest_root, basetemp_root):
        path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HYDROMODPY_TEST_SCRATCH_ROOT"] = str(scratch_root)
    env["HYDROMODPY_TEST_SESSION_SCRATCH_ROOT"] = str(session_root)
    env["PYTEST_DEBUG_TEMPROOT"] = str(pytest_root)
    env["TMPDIR"] = str(tmp_root)
    env["TMP"] = str(tmp_root)
    env["TEMP"] = str(tmp_root)
    return basetemp_root, env


__all__ = (
    "EXIT_OK",
    "EXIT_CONFIG",
    "EXIT_RUN_FAILED",
    "EXIT_NOT_FOUND",
    "EXIT_USER_ABORT",
    "EXIT_DATA_ERROR",
    "EXIT_SOLVER_ERROR",
    "EXIT_SIGINT",
    "find_project_root",
    "find_catalog_root",
    "find_workspace_root",
    "find_data_workspace",
    "resolve_workspace",
    "resolve_sim_id",
    "auto_scan_workspace",
    "resolve_test_scratch_root",
    "resolve_test_session_scratch_root",
    "pytest_addopts_declares_basetemp",
    "build_pytest_runtime_env",
)
