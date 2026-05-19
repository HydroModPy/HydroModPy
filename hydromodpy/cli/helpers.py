"""Shared CLI helpers: exit codes, error formatting, workspace lookups."""

from __future__ import annotations

import os
import re
import sys
import tempfile
import uuid
from pathlib import Path

from hydromodpy.core.state.paths import CATALOG_FILENAME

# ---------------------------------------------------------------------------
# Standardised exit codes (interface refactor, see reports/99_target_architecture.md §5.3).
# Typed codes 10..19 map onto specific exception classes; 0/1/2 keep their
# POSIX-conventional meaning; 130 is the standard SIGINT termination code.
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_USAGE = 2
EXIT_NOT_FOUND = 10
EXIT_SCHEMA_MISMATCH = 11
EXIT_WRITE_CONFLICT = 12
EXIT_READ_ONLY = 13
EXIT_CONFIG = 14
EXIT_SOLVER_ERROR = 15
EXIT_VALIDATION = 16
EXIT_CROSS_PROJECTS = 17
EXIT_BACKUP_FAILED = 18
EXIT_MIGRATION_FAILED = 19
EXIT_SIGINT = 130

# Legacy aliases kept for backwards compatibility with existing call sites
# that have not been migrated to the typed scheme yet. New code should use
# the named ``EXIT_*`` constants above.
EXIT_RUN_FAILED = EXIT_GENERIC
EXIT_USER_ABORT = EXIT_SIGINT
EXIT_DATA_ERROR = EXIT_VALIDATION


def exit_code_for(exc: BaseException) -> int:
    """Map an exception instance to the matching typed exit code.

    Returns :data:`EXIT_GENERIC` when no specific mapping is registered.
    :class:`KeyboardInterrupt` is routed to :data:`EXIT_SIGINT` (POSIX 130).
    """
    from hydromodpy.core import exceptions as hmp_exc

    if isinstance(exc, KeyboardInterrupt):
        return EXIT_SIGINT
    if isinstance(exc, FileNotFoundError):
        return EXIT_NOT_FOUND
    mapping: tuple[tuple[type[BaseException], int], ...] = (
        (getattr(hmp_exc, "SchemaVersionMismatchError", type("_n", (), {})), EXIT_SCHEMA_MISMATCH),
        (getattr(hmp_exc, "WriteConflictError", type("_n", (), {})), EXIT_WRITE_CONFLICT),
        (getattr(hmp_exc, "ReadOnlyError", type("_n", (), {})), EXIT_READ_ONLY),
        (getattr(hmp_exc, "ConfigError", type("_n", (), {})), EXIT_CONFIG),
        (getattr(hmp_exc, "ConfigMissingError", type("_n", (), {})), EXIT_CONFIG),
        (getattr(hmp_exc, "SolverError", type("_n", (), {})), EXIT_SOLVER_ERROR),
        (getattr(hmp_exc, "DataError", type("_n", (), {})), EXIT_VALIDATION),
        (getattr(hmp_exc, "CrossProjectsError", type("_n", (), {})), EXIT_CROSS_PROJECTS),
        (getattr(hmp_exc, "BackupFailedError", type("_n", (), {})), EXIT_BACKUP_FAILED),
        (getattr(hmp_exc, "MigrationFailedError", type("_n", (), {})), EXIT_MIGRATION_FAILED),
    )
    for exc_type, code in mapping:
        if isinstance(exc, exc_type):
            return code
    return EXIT_GENERIC


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
        if (parent / CATALOG_FILENAME).exists():
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
    override = os.environ.get("HMP_TEST_SCRATCH_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return (Path(tempfile.gettempdir()) / "hydromodpy_tests").resolve()


def resolve_test_session_scratch_root(scratch_root: Path) -> Path:
    """Return the pytest scratch root for this CLI-launched test process tree."""
    override = os.environ.get("HMP_TEST_SESSION_SCRATCH_ROOT")
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
    env["HMP_TEST_SCRATCH_ROOT"] = str(scratch_root)
    env["HMP_TEST_SESSION_SCRATCH_ROOT"] = str(session_root)
    env["PYTEST_DEBUG_TEMPROOT"] = str(pytest_root)
    env["TMPDIR"] = str(tmp_root)
    env["TMP"] = str(tmp_root)
    env["TEMP"] = str(tmp_root)
    return basetemp_root, env


__all__ = (
    "EXIT_OK",
    "EXIT_GENERIC",
    "EXIT_USAGE",
    "EXIT_NOT_FOUND",
    "EXIT_SCHEMA_MISMATCH",
    "EXIT_WRITE_CONFLICT",
    "EXIT_READ_ONLY",
    "EXIT_CONFIG",
    "EXIT_SOLVER_ERROR",
    "EXIT_VALIDATION",
    "EXIT_CROSS_PROJECTS",
    "EXIT_BACKUP_FAILED",
    "EXIT_MIGRATION_FAILED",
    "EXIT_SIGINT",
    "EXIT_RUN_FAILED",
    "EXIT_USER_ABORT",
    "EXIT_DATA_ERROR",
    "exit_code_for",
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
