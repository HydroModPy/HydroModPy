"""Shared CLI helpers: exit codes, error formatting, workspace lookups."""

from __future__ import annotations

import os
import re
import sys
import tempfile
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger

# ---------------------------------------------------------------------------
# Standardised exit codes for the hmp CLI. The shared grammar that emits them
# lives in ``hydromodpy/cli/_conventions.py``. Typed codes 10..23 map onto
# specific exception classes; 0/1/2 keep their POSIX-conventional meaning;
# 130 is the standard SIGINT termination code.
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
EXIT_AMBIGUOUS_REFERENCE = 20
EXIT_CALIBRATION = 21
EXIT_CATALOG_UNREADABLE = 22
# A launch of several cases that ran to its end with at least one case
# failed. Apart from a crash (1), so a CI job can tell the two.
EXIT_CASES_FAILED = 23
EXIT_SIGINT = 130


def exit_code_for(exc: BaseException) -> int:
    """Map an exception instance to the matching typed exit code.

    Returns :data:`EXIT_GENERIC` when no specific mapping is registered.
    :class:`KeyboardInterrupt` is routed to :data:`EXIT_SIGINT` (POSIX 130).
    """
    from hydromodpy.core.exceptions import (
        BackupFailedError,
        CalibrationError,
        CapabilityVersionMismatchError,
        CatalogUnreadableError,
        ConfigError,
        ConfigMissingError,
        CrossProjectsError,
        DataError,
        FailedCasesError,
        ImportConflictError,
        JobUsageError,
        MigrationFailedError,
        ReadOnlyError,
        SolverError,
        StepError,
        TerrainError,
        WriteConflictError,
    )
    from hydromodpy.results.catalog.discovery import (
        AmbiguousReferenceError,
        SimulationNotFoundError,
    )
    from hydromodpy.results.errors import SchemaVersionMismatchError
    from hydromodpy.results.storage.attempt import (
        AttemptClaimedError,
        CaseAliveError,
        DirectoryWithoutOutcomeError,
    )

    if isinstance(exc, KeyboardInterrupt):
        return EXIT_SIGINT
    if isinstance(exc, StepError):
        # The pipeline wraps whatever a step raised. The category of the run
        # is the one of that cause: a data step that could not load its gauge
        # exits as a data failure, not as a generic error.
        return exit_code_for(exc.cause)
    if isinstance(exc, FailedCasesError):
        return EXIT_CASES_FAILED
    if isinstance(exc, AmbiguousReferenceError):
        return EXIT_AMBIGUOUS_REFERENCE
    if isinstance(exc, SimulationNotFoundError):
        return EXIT_NOT_FOUND
    if isinstance(exc, FileNotFoundError):
        return EXIT_NOT_FOUND
    mapping: tuple[tuple[type[BaseException], int], ...] = (
        (JobUsageError, EXIT_USAGE),
        (CapabilityVersionMismatchError, EXIT_SCHEMA_MISMATCH),
        (SchemaVersionMismatchError, EXIT_SCHEMA_MISMATCH),
        (WriteConflictError, EXIT_WRITE_CONFLICT),
        # The archive collides with a row the catalog holds: a write conflict
        # that --force or --as resolves, not a concurrent writer.
        (ImportConflictError, EXIT_WRITE_CONFLICT),
        (ReadOnlyError, EXIT_READ_ONLY),
        # The directory of the case is held by another worker, or says
        # nothing about itself: a conflict with what is on disk, which the
        # worker reports in one sentence and never repairs.
        (AttemptClaimedError, EXIT_WRITE_CONFLICT),
        (CaseAliveError, EXIT_WRITE_CONFLICT),
        (DirectoryWithoutOutcomeError, EXIT_WRITE_CONFLICT),
        # The directory a move or a reservation targets is already there: a
        # paired run directory taken, a restore onto a live name.
        (FileExistsError, EXIT_WRITE_CONFLICT),
        (ConfigError, EXIT_CONFIG),
        (ConfigMissingError, EXIT_CONFIG),
        (SolverError, EXIT_SOLVER_ERROR),
        # A terrain engine is the geospatial backend of a capability, and what
        # code 15 means at a process boundary is "the backend failed". The
        # whole family maps to it: its four classes differ in what a caller
        # does next inside the process, not in what an orchestrator does with
        # the exit status.
        (TerrainError, EXIT_SOLVER_ERROR),
        (DataError, EXIT_VALIDATION),
        (CrossProjectsError, EXIT_CROSS_PROJECTS),
        (BackupFailedError, EXIT_BACKUP_FAILED),
        (MigrationFailedError, EXIT_MIGRATION_FAILED),
        (CatalogUnreadableError, EXIT_CATALOG_UNREADABLE),
        # Last of the list on purpose: CalibrationError is a sibling of the
        # others, but ObjectiveError and OptimizerError derive from it, so a
        # more specific mapping would have to come before this one.
        (CalibrationError, EXIT_CALIBRATION),
    )
    for exc_type, code in mapping:
        if isinstance(exc, exc_type):
            return code
    return EXIT_GENERIC


def exit_if_promotion_failed(result: Any) -> None:
    """Name each failed promotion, then exit with the calibration code.

    Called once the search results are printed: they stay valid and are kept,
    only the replayed runs are missing. Returns when every promotion succeeded.
    """
    from hydromodpy.calibration.report import promotion_failures
    from hydromodpy.core.exceptions import CalibrationError

    failures = promotion_failures(result)
    if not failures:
        return
    for line in failures:
        print(f"  Promotion failed: {line}", file=sys.stderr)
    sys.exit(exit_code_for(CalibrationError(f"{len(failures)} promotion(s) failed")))


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


def find_data_workspace(start: Path) -> Path | None:
    """Walk up from ``start`` to find a workspace root (has a ``data/`` folder)."""
    for parent in [start] + list(start.parents):
        if not parent.is_dir():
            continue
        if (parent / "data").is_dir() and (
            (parent / "projects").is_dir() or (parent / "workspace.toml").exists()
        ):
            return parent
    return None


def find_workspace(workspace_arg: str | None) -> Path | None:
    """Return the workspace named by ``-w``, by ``HMP_WORKSPACE``, or above the cwd.

    A named project directory resolves to the workspace that holds it; a named
    directory that carries ``data/``, ``projects/`` or ``workspace.toml`` is
    the workspace. Returns ``None`` when nothing answers: there is no default
    folder such as ``~/hydromodpy``.
    """
    from hydromodpy.core.state.paths import is_workspace_root

    named = workspace_arg or os.environ.get("HMP_WORKSPACE")
    start = Path(named).expanduser().resolve() if named else Path.cwd().resolve()
    if not start.is_dir():
        return None
    found = find_data_workspace(start)
    if found is None and (is_workspace_root(start) or (named and (start / "data").is_dir())):
        found = start
    return found


def resolve_workspace(workspace_arg: str | None) -> Path:
    """Return :func:`find_workspace`, or stop with :data:`EXIT_NOT_FOUND` naming ``-w``."""
    found = find_workspace(workspace_arg)
    if found is not None:
        return found
    named = workspace_arg or os.environ.get("HMP_WORKSPACE")
    start = Path(named).expanduser().resolve() if named else Path.cwd().resolve()
    if not start.is_dir():
        print(
            f"Workspace {start} does not exist. Run 'hmp workspace init {start}' first.",
            file=sys.stderr,
        )
    else:
        print(
            f"No HydroModPy workspace at or above {start}. Name one with -w, "
            "or run 'hmp workspace init' first.",
            file=sys.stderr,
        )
    sys.exit(EXIT_NOT_FOUND)


def resolve_project(workspace_arg: str | None) -> Path:
    """Return the project named by ``-w``, or the one that holds the cwd.

    The project is the directory that carries ``project.toml`` (or an index).
    Without one, the command stops with :data:`EXIT_NOT_FOUND`.
    """
    from hydromodpy.core.state.paths import (
        PROJECT_MARKER_FILENAME,
        is_project_root,
        resolve_project_root,
    )

    start = Path(workspace_arg).expanduser().resolve() if workspace_arg else Path.cwd().resolve()
    root = resolve_project_root(start)
    if not is_project_root(root):
        print(
            f"No {PROJECT_MARKER_FILENAME} at or above {start}. Name the project with -w.",
            file=sys.stderr,
        )
        sys.exit(EXIT_NOT_FOUND)
    return root


def resolve_named_project(workspace_arg: str | None, name: str | None) -> Path:
    """Return ``projects/<name>`` of the workspace, or the project of ``-w`` without a name.

    Stops with :data:`EXIT_NOT_FOUND` when the directory does not exist.
    """
    if name is None:
        return resolve_project(workspace_arg)
    from hydromodpy.core.state.paths import PROJECTS_DIRNAME

    project_dir = resolve_workspace(workspace_arg) / PROJECTS_DIRNAME / name
    if not project_dir.is_dir():
        print(f"No such project: {project_dir}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    return project_dir


# ---------------------------------------------------------------------------
# Auto-scan workspace for drag-and-drop custom folders
# ---------------------------------------------------------------------------


def apply_verbosity(args: Any, raw_toml: Mapping[str, Any]) -> str:
    """Set the console verbosity of this command and return the level applied.

    Precedence, first source that names one wins: the CLI flag, then
    ``HMP_VERBOSITY``, then ``[workflow] verbosity`` in the config, then the
    default. Called before anything prints, so the banner obeys it too.
    """
    from hydromodpy.core.logging import (
        DEFAULT_VERBOSITY,
        set_verbosity,
        verbosity_from_env,
    )

    declared = None
    workflow_section = raw_toml.get("workflow") if isinstance(raw_toml, Mapping) else None
    if isinstance(workflow_section, Mapping):
        declared = workflow_section.get("verbosity")

    level = getattr(args, "verbosity", None) or verbosity_from_env() or declared
    try:
        return set_verbosity(level or DEFAULT_VERBOSITY)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_CONFIG)


def auto_scan_workspace(config_path: Path) -> None:
    """Best-effort scan of drag-and-drop custom folders before a run.

    ``scan_custom`` already logs what it changed. Only what went wrong is
    reported here, as a warning, so it survives a quiet run.
    """
    logger = get_logger(__name__)
    try:
        project_dir = config_path.parent.resolve()
        ws = find_data_workspace(project_dir)
        if ws is None:
            return
        from hydromodpy.data.workspace.custom_scan import scan_custom

        report = scan_custom(ws)
        for path, msg in report.errors[:5]:
            logger.warning("auto_scan could not read %s: %s", path, msg)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("auto_scan skipped (%s: %s)", type(exc).__name__, exc)


# ---------------------------------------------------------------------------
# Profiling (--profile flag, pyinstrument)
# ---------------------------------------------------------------------------


def _require_pyinstrument() -> None:
    """Exit with :data:`EXIT_CONFIG` when pyinstrument is not installed."""
    try:
        import pyinstrument  # noqa: F401
    except ImportError:
        print(
            "pyinstrument is required for --profile. Install it with: pip install pyinstrument",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)


def profile_arg_from_toml(raw_toml: Mapping[str, Any]) -> str | None:
    """Map ``[workflow].profile`` to the ``--profile`` argument convention."""
    workflow_section = raw_toml.get("workflow")
    if not isinstance(workflow_section, dict):
        return None
    value = workflow_section.get("profile")
    if value is True:
        return ""
    if isinstance(value, str) and value:
        return value
    return None


def resolve_profile_output(profile_arg: str | None, config_path: Path) -> Path | None:
    """Resolve the ``--profile`` argument to an HTML report path.

    ``None`` means profiling is disabled. An empty string (bare ``--profile``)
    defaults to ``<config>.profile.html`` next to the config. Fails fast when
    profiling is requested but pyinstrument is missing.
    """
    if profile_arg is None:
        return None
    _require_pyinstrument()
    if profile_arg:
        return Path(profile_arg).expanduser().resolve()
    return config_path.with_suffix(".profile.html")


@contextmanager
def profile_run(output: Path | None, *, description: str | None = None) -> Iterator[None]:
    """Profile the wrapped block with pyinstrument.

    No-op when ``output`` is None. ``description`` labels the report header
    (defaults to pyinstrument's call-site text). Writes the HTML report to
    ``output`` and prints the call-tree summary to stderr, even when the
    block raises or is interrupted. Exits with :data:`EXIT_CONFIG` when
    pyinstrument is missing.
    """
    if output is None:
        yield
        return
    _require_pyinstrument()
    from pyinstrument import Profiler

    profiler = Profiler()
    profiler.start(target_description=description)
    try:
        yield
    finally:
        profiler.stop()
        # Best-effort emission: a report failure must never mask the run
        # outcome or replace its typed exit code.
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(profiler.output_html(), encoding="utf-8")
            print(profiler.output_text(unicode=True, color=sys.stderr.isatty()), file=sys.stderr)
            print(f"  Profile report: {output}", file=sys.stderr)
        except Exception as exc:
            print(f"  WARNING: profile report write failed: {exc}", file=sys.stderr)


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
    "EXIT_AMBIGUOUS_REFERENCE",
    "EXIT_CALIBRATION",
    "EXIT_CATALOG_UNREADABLE",
    "EXIT_CASES_FAILED",
    "EXIT_SIGINT",
    "exit_code_for",
    "exit_if_promotion_failed",
    "find_project_root",
    "find_workspace_root",
    "find_data_workspace",
    "find_workspace",
    "resolve_workspace",
    "resolve_project",
    "resolve_named_project",
    "apply_verbosity",
    "auto_scan_workspace",
    "profile_arg_from_toml",
    "resolve_profile_output",
    "profile_run",
    "resolve_test_scratch_root",
    "resolve_test_session_scratch_root",
    "pytest_addopts_declares_basetemp",
    "build_pytest_runtime_env",
)
