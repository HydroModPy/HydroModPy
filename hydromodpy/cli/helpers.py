"""Shared CLI helpers: exit codes, error formatting, workspace lookups, override flags."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NoReturn

from hydromodpy.cli.output import failed
from hydromodpy.core.exceptions import (
    CalibrationError,
    CommandUsageError,
    ConfigError,
    DataError,
    FailedCasesError,
    HydroModPyError,
    NothingThereError,
    StepError,
    WriteConflictError,
)

# ---------------------------------------------------------------------------
# Standardized exit codes for the hmp CLI. The shared grammar that emits them
# lives in ``hydromodpy/cli/conventions.py``. Typed codes 10..23 map onto
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
        CapabilityVersionMismatchError,
        CatalogUnreadableError,
        ConfigMissingError,
        CrossProjectsError,
        ImportConflictError,
        JobUsageError,
        MigrationFailedError,
        ReadOnlyError,
        SchemaVersionMismatchError,
        SolverError,
        TerrainError,
    )
    from hydromodpy.results.catalog.discovery import (
        AmbiguousReferenceError,
        SimulationNotFoundError,
    )
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
        (CommandUsageError, EXIT_USAGE),
        (JobUsageError, EXIT_USAGE),
        (CapabilityVersionMismatchError, EXIT_SCHEMA_MISMATCH),
        (SchemaVersionMismatchError, EXIT_SCHEMA_MISMATCH),
        (WriteConflictError, EXIT_WRITE_CONFLICT),
        # The archive collides with a row the catalog holds: a write conflict
        # that --name resolves, not a concurrent writer.
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


_CLASS_OF_EXIT: dict[int, type[HydroModPyError]] = {
    EXIT_GENERIC: HydroModPyError,
    EXIT_USAGE: CommandUsageError,
    EXIT_NOT_FOUND: NothingThereError,
    EXIT_WRITE_CONFLICT: WriteConflictError,
    EXIT_CONFIG: ConfigError,
    EXIT_VALIDATION: DataError,
    EXIT_CALIBRATION: CalibrationError,
    EXIT_CASES_FAILED: FailedCasesError,
}
"""The class whose ``HMPY.Exxx`` a failure carries when no exception of ours names its own."""


def _class_of(exc: BaseException | None, exit_code: int) -> type[HydroModPyError]:
    """Return the class that names a failure: the one raised, else the one of its exit code."""
    while isinstance(exc, StepError):
        exc = exc.cause
    if isinstance(exc, HydroModPyError):
        return type(exc)
    return _CLASS_OF_EXIT.get(exit_code, HydroModPyError)


def error_code(exc: BaseException) -> str:
    """Return the ``HMPY.Exxx`` code a failure prints.

    The pipeline wraps what a step raised, so the code is the one of that cause, as
    the exit code is. A builtin raised by HydroModPy takes the code of its exit code,
    and ``HMPY.E000`` when it has none: that is a bug of ours, not of the caller.
    """
    return _class_of(exc, exit_code_for(exc)).code


def _leave(message: str, klass: type[HydroModPyError], code: str, exit_code: int) -> NoReturn:
    """Print the failure on stderr, with its code first, and end with its exit code."""
    print(f"{code}: {message}", file=sys.stderr)
    title = "A failure with no category of its own" if klass is HydroModPyError else klass.title()
    failed(code, title, message, exit_code)
    sys.exit(exit_code)


def fail(exc: BaseException) -> NoReturn:
    """End the command on an exception: its code, its message, its exit code.

    An interruption is no failure of the command, so it carries no code.
    """
    exit_code = exit_code_for(exc)
    if isinstance(exc, KeyboardInterrupt):
        print(str(exc) or "Interrupted.", file=sys.stderr)
        sys.exit(exit_code)
    klass = _class_of(exc, exit_code)
    _leave(str(exc) or type(exc).__name__, klass, klass.code, exit_code)


def refuse(message: str, exit_code: int, *, cause: BaseException | None = None) -> NoReturn:
    """End the command on a refusal of its own, in words of its own.

    It carries the code of *cause*, when it comes from one, else the code of
    the class of its exit code.
    """
    klass = _class_of(cause, exit_code)
    _leave(message, klass, klass.code, exit_code)


def confirm(args: Any, question: str, *, doing: str) -> None:
    """Return once the user agreed: ``-y``, or a yes on a terminal. Stops otherwise.

    Without a terminal and without ``-y``, *doing* names what is refused.
    """
    if args.yes:
        return
    if not sys.stdin.isatty():
        refuse(f"Refusing to {doing} without -y in non-interactive mode.", EXIT_USAGE)
    try:
        answer = input(f"{question} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.", file=sys.stderr)
        sys.exit(EXIT_SIGINT)
    if answer not in {"y", "yes"}:
        print("Aborted.", file=sys.stderr)
        sys.exit(EXIT_SIGINT)


def exit_if_session_unfinished(result: Any) -> None:
    """Say why a calibration session did not complete, then exit with the calibration code.

    Called once the search results are printed: they stay in the session
    folder. A failed promotion is named run by run, since it leaves a replayed
    run missing and closes the session ``partial``. A session closed
    ``failed``, ``partial`` or ``aborted`` for another reason is named with
    the reason ``session.json`` gives. Returns when the session completed.
    """
    from hydromodpy.calibration.report import promotion_failures, unfinished_session

    failures = promotion_failures(result)
    for line in failures:
        print(f"  Promotion failed: {line}", file=sys.stderr)
    unfinished = None if failures else unfinished_session(result)
    if unfinished is not None:
        print(f"  {unfinished}.", file=sys.stderr)
    if failures or unfinished is not None:
        refuse("the calibration session did not complete", EXIT_CALIBRATION)


# ---------------------------------------------------------------------------
# Workspace / project discovery
# ---------------------------------------------------------------------------


def resolve_workspace(workspace_arg: str | None) -> Path:
    """Return :func:`~hydromodpy.core.workspace.resolve.find_workspace`, or stop with :data:`EXIT_NOT_FOUND` naming ``-w``."""
    from hydromodpy.core.workspace.resolve import find_workspace
    from hydromodpy.core.workspace.workspace_toml import refuse_a_newer_workspace

    found = find_workspace(workspace_arg)
    if found is not None:
        refuse_a_newer_workspace(found)
        return found
    named = workspace_arg or os.environ.get("HMP_WORKSPACE")
    start = Path(named).expanduser().resolve() if named else Path.cwd().resolve()
    if not start.is_dir():
        refuse(
            f"Workspace {start} does not exist. Run 'hmp workspace init {start}' first.",
            EXIT_NOT_FOUND,
        )
    refuse(
        f"No HydroModPy workspace at or above {start}. Name one with -w, "
        "or run 'hmp workspace init' first.",
        EXIT_NOT_FOUND,
    )


def resolve_project(workspace_arg: str | None) -> Path:
    """Return the project named by ``-w``, or the one that holds the cwd.

    The project is the directory that carries ``project.toml`` (or an index).
    Without one, the command stops with :data:`EXIT_NOT_FOUND`.
    """
    from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME, is_project_root
    from hydromodpy.core.state.result_dirs import resolve_project_root

    start = Path(workspace_arg).expanduser().resolve() if workspace_arg else Path.cwd().resolve()
    root = resolve_project_root(start)
    if not is_project_root(root):
        refuse(
            f"No {PROJECT_MARKER_FILENAME} at or above {start}. Name the project with -w.",
            EXIT_NOT_FOUND,
        )
    return root


def project_root_of(args: Any) -> Path:
    """Return the project root ``-w`` names, or the one around the current directory.

    Nothing is checked: a verb that reads an index refuses when it finds none.
    """
    from hydromodpy.core.state.result_dirs import resolve_project_root

    named = getattr(args, "workspace", None)
    return resolve_project_root(Path(named or Path.cwd()).expanduser().resolve())


def base_named_by_w(workspace_arg: str | None) -> Path | None:
    """Return the project ``-w`` names, the base of a TOML verb, or ``None`` without ``-w``.

    A verb passes it to the loader as an argument. Without ``-w`` the base is the
    one the file gives: the project root above it.
    """
    return resolve_project(workspace_arg) if workspace_arg else None


def resolve_project_ref(workspace_arg: str | None, ref: str | None) -> Path:
    """Return the project a reference names: a path is read as a path, a bare name under projects/.

    A path is ``.``, ``..``, anything with a slash or an absolute path: the
    project at or above it. Nothing found stops with :data:`EXIT_NOT_FOUND`.
    """
    if ref is None:
        return resolve_project(workspace_arg)
    from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME, PROJECTS_DIRNAME

    if not _is_path_ref(ref):
        project_dir = resolve_workspace(workspace_arg) / PROJECTS_DIRNAME / ref
        if not project_dir.is_dir():
            refuse(f"No such project: {project_dir}", EXIT_NOT_FOUND)
        return project_dir
    from hydromodpy.core.state.result_dirs import resolve_project_root

    start = Path(ref).expanduser().resolve()
    root = resolve_project_root(start)
    if not (root / PROJECT_MARKER_FILENAME).is_file():
        refuse(
            f"No {PROJECT_MARKER_FILENAME} at or above {start}: name a project directory, "
            "or a project name under projects/ of the workspace.",
            EXIT_NOT_FOUND,
        )
    return root


def _is_path_ref(ref: str) -> bool:
    return ref in (".", "..") or "/" in ref or Path(ref).expanduser().is_absolute()


# ---------------------------------------------------------------------------
# Console verbosity
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
        refuse(str(exc), EXIT_CONFIG, cause=exc)


# ---------------------------------------------------------------------------
# Overrides of a TOML verb: --overlay, --set and HMP_SET_*
# ---------------------------------------------------------------------------


def add_override_arguments(parser: argparse.ArgumentParser) -> None:
    """Register ``--overlay`` and ``--set``, the flags that change a document on its way in."""
    parser.add_argument(
        "--overlay",
        action="append",
        default=[],
        type=Path,
        help="TOML overlay applied after base_config inheritance. Repeatable.",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        dest="set_overrides",
        metavar="PATH=VALUE",
        help="Dotted TOML override applied after overlays, e.g. flow.param.K.field.value=2e-5.",
    )


def changes_of_args(args: Any, env: Mapping[str, str]) -> dict[str, Any]:
    """Return what ``--set`` and the ``HMP_SET_*`` variables of *env* change, by dotted path.

    The items of ``--set`` come first, in the order written, then the variables,
    which win, as they always did. A key is told in the form it was written, so
    an old name is told when the document is loaded.

    Raises
    ------
    ValueError
        On an item that is not ``PATH=VALUE`` or whose path does not parse.
    """
    from hydromodpy.core.toml_io.overrides import (
        ENV_PATH_SEPARATOR,
        ENV_SET_PREFIX,
        env_set_names,
        parse_override_value,
    )
    from hydromodpy.core.toml_io.paths import parse

    changes: dict[str, Any] = {}
    for item in getattr(args, "set_overrides", None) or []:
        if "=" not in item:
            raise ValueError(f"--set expects PATH=VALUE, got {item!r}")
        dotted, raw = item.split("=", 1)
        changes[str(parse(dotted.strip()))] = parse_override_value(raw)
    for name in env_set_names(env):
        # The case after the prefix is the case of the key, as it always was.
        dotted = name[len(ENV_SET_PREFIX) :].replace(ENV_PATH_SEPARATOR, ".")
        changes[str(parse(dotted))] = parse_override_value(env[name])
    return changes


def with_changes(document: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of *document* with *changes*, a mapping of dotted paths to values, set on it.

    It is the document a verb looks at (its sections, its verbosity); the loader
    applies the same changes again, as a layer of their own, when it validates.
    """
    import copy

    from hydromodpy.core.toml_io.paths import assign

    changed = copy.deepcopy(dict(document))
    for dotted, value in changes.items():
        assign(changed, dotted, value)
    return changed


def toml_target(config: str | Path) -> Path:
    """Return the TOML file a verb was given, or stop: missing is 10, another suffix is 14."""
    target = Path(config).expanduser().resolve()
    if not target.is_file():
        refuse(f"File not found: {target}", EXIT_NOT_FOUND)
    if target.suffix != ".toml":
        refuse(f"Expected a .toml file, got: {target.suffix}", EXIT_CONFIG)
    return target


def profile_output_of(
    args: argparse.Namespace, raw_toml: Mapping[str, Any], target: Path
) -> Path | None:
    """Return where ``--profile``, else ``[workflow] profile``, writes its report, or ``None``."""
    profile_arg = getattr(args, "profile", None)
    if profile_arg is None and raw_toml:
        profile_arg = profile_arg_from_toml(raw_toml)
    return resolve_profile_output(profile_arg, target)


# ---------------------------------------------------------------------------
# Profiling (--profile flag, pyinstrument)
# ---------------------------------------------------------------------------


def _require_pyinstrument() -> None:
    """Exit with :data:`EXIT_CONFIG` when pyinstrument is not installed."""
    try:
        import pyinstrument  # noqa: F401
    except ImportError:
        refuse(
            "pyinstrument is required for --profile. Install it with: pip install pyinstrument",
            EXIT_CONFIG,
        )


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
    "confirm",
    "error_code",
    "exit_code_for",
    "exit_if_session_unfinished",
    "fail",
    "base_named_by_w",
    "project_root_of",
    "refuse",
    "resolve_workspace",
    "resolve_project",
    "add_override_arguments",
    "apply_verbosity",
    "changes_of_args",
    "profile_arg_from_toml",
    "profile_output_of",
    "resolve_profile_output",
    "profile_run",
    "toml_target",
    "with_changes",
)
