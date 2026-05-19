"""In-process invocation helper for the ``hmp`` CLI used by unit tests.

Argparse-based equivalent of click's ``CliRunner``: redirect stdout / stderr,
intercept ``SystemExit``, collect the exit code, and return a result object.
Avoids launching a subprocess so tests stay fast and can patch internals.
"""

from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass


@dataclass
class CliResult:
    """Outcome of a single ``CliRunner.invoke`` call.

    ``exit_code`` is the numeric code returned via ``SystemExit`` (or ``0`` if
    the dispatcher returned normally). ``stdout`` and ``stderr`` are the
    captured streams. ``exception`` is the unraised exception when the CLI
    raised something other than ``SystemExit``.
    """

    exit_code: int
    stdout: str
    stderr: str
    exception: BaseException | None = None

    @property
    def output(self) -> str:
        return self.stdout

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class CliRunner:
    """Invoke the hydromodpy CLI in-process and capture stdio + exit code."""

    def __init__(self, *, catch_exceptions: bool = True) -> None:
        self._catch_exceptions = catch_exceptions

    def invoke(self, args: list[str] | tuple[str, ...]) -> CliResult:
        """Run ``hmp <args>`` in-process.

        The CLI entry point is reloaded for each invocation so argparse builds
        a fresh subparser tree. ``SystemExit`` is caught and translated into
        ``exit_code``; any other exception bubbles only when ``catch_exceptions``
        is False at construction time.
        """
        from hydromodpy.cli.main import main as cli_main

        argv = list(args)
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        exit_code = 0
        exception: BaseException | None = None

        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            try:
                cli_main(argv)
            except SystemExit as exc:
                code = exc.code
                if code is None:
                    exit_code = 0
                elif isinstance(code, int):
                    exit_code = code
                else:
                    stderr_buf.write(str(code))
                    exit_code = 1
            except BaseException as exc:
                if not self._catch_exceptions:
                    raise
                exception = exc
                exit_code = 1

        return CliResult(
            exit_code=exit_code,
            stdout=stdout_buf.getvalue(),
            stderr=stderr_buf.getvalue(),
            exception=exception,
        )


__all__ = ["CliRunner", "CliResult"]
