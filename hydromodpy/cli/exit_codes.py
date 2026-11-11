"""Exit codes of the hmp CLI and the functions that end a command with one."""

from __future__ import annotations

import sys
from typing import Any, NoReturn

from hydromodpy.cli.output import failed
from hydromodpy.core.exceptions import (
    CalibrationError,
    Category,
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


EXIT_CODE_OF: dict[Category, int] = {
    Category.GENERIC: EXIT_GENERIC,
    Category.USAGE: EXIT_USAGE,
    Category.NOT_FOUND: EXIT_NOT_FOUND,
    Category.SCHEMA_MISMATCH: EXIT_SCHEMA_MISMATCH,
    Category.WRITE_CONFLICT: EXIT_WRITE_CONFLICT,
    Category.READ_ONLY: EXIT_READ_ONLY,
    Category.CONFIG: EXIT_CONFIG,
    Category.SOLVER: EXIT_SOLVER_ERROR,
    Category.DATA: EXIT_VALIDATION,
    Category.CROSS_PROJECTS: EXIT_CROSS_PROJECTS,
    Category.BACKUP_FAILED: EXIT_BACKUP_FAILED,
    Category.MIGRATION_FAILED: EXIT_MIGRATION_FAILED,
    Category.AMBIGUOUS_REFERENCE: EXIT_AMBIGUOUS_REFERENCE,
    Category.CALIBRATION: EXIT_CALIBRATION,
    Category.CATALOG_UNREADABLE: EXIT_CATALOG_UNREADABLE,
    Category.CASES_FAILED: EXIT_CASES_FAILED,
}
"""The exit code of each category. An exception says its category, this table says the number."""


def exit_code_for(exc: BaseException) -> int:
    """Map an exception instance to the exit code of its category.

    A :class:`~hydromodpy.core.exceptions.HydroModPyError` carries its
    category, and :data:`EXIT_CODE_OF` gives the code. The pipeline wraps what
    a step raised, so a :class:`~hydromodpy.core.exceptions.StepError` takes
    the code of its cause. A ``FileNotFoundError`` or a ``FileExistsError``
    raised outside our hierarchy reads as not found and as a write conflict.
    Anything else is :data:`EXIT_GENERIC`. :class:`KeyboardInterrupt` is
    :data:`EXIT_SIGINT` (POSIX 130).
    """
    if isinstance(exc, KeyboardInterrupt):
        return EXIT_SIGINT
    if isinstance(exc, StepError):
        return exit_code_for(exc.cause)
    if isinstance(exc, HydroModPyError):
        return EXIT_CODE_OF[type(exc).category]
    if isinstance(exc, FileNotFoundError):
        return EXIT_NOT_FOUND
    if isinstance(exc, FileExistsError):
        # The directory a move or a reservation targets is already there: a
        # paired run directory taken, a restore onto a live name.
        return EXIT_WRITE_CONFLICT
    return EXIT_GENERIC


_CLASS_OF_CATEGORY: dict[Category, type[HydroModPyError]] = {
    Category.GENERIC: HydroModPyError,
    Category.USAGE: CommandUsageError,
    Category.NOT_FOUND: NothingThereError,
    Category.WRITE_CONFLICT: WriteConflictError,
    Category.CONFIG: ConfigError,
    Category.DATA: DataError,
    Category.CALIBRATION: CalibrationError,
    Category.CASES_FAILED: FailedCasesError,
}
_CLASS_OF_EXIT: dict[int, type[HydroModPyError]] = {
    EXIT_CODE_OF[category]: klass for category, klass in _CLASS_OF_CATEGORY.items()
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
    "EXIT_CODE_OF",
    "confirm",
    "error_code",
    "exit_code_for",
    "exit_if_session_unfinished",
    "fail",
    "refuse",
)
