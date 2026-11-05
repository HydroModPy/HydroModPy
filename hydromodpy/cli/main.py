"""Top-level CLI dispatcher for HydroModPy.

Builds the argparse tree from :mod:`hydromodpy.cli.commands` and invokes
the subcommand handler attached via ``parser.set_defaults(_handler=...)``.
Unhandled exceptions are mapped to typed exit codes by
:func:`hydromodpy.cli.helpers.exit_code_for` so the shell sees a meaningful
status (POSIX-conventional 130 for SIGINT, 10..23 for specific failure
categories).
"""

# PYTHON_ARGCOMPLETE_OK

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_USAGE, fail


def _version_string() -> str:
    from hydromodpy.core.version import __version__ as hmp_version

    parts = [
        f"hydromodpy {hmp_version}",
        f"python {platform.python_version()}",
        f"{platform.system()} {platform.release()} ({platform.machine()})",
    ]
    try:
        import subprocess

        git = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if git.returncode == 0 and git.stdout.strip():
            parts.append(f"git {git.stdout.strip()}")
    except Exception:  # pragma: no cover - optional
        pass
    return " | ".join(parts)


def _build_parser() -> argparse.ArgumentParser:
    from hydromodpy.cli.commands import ALL_COMMANDS
    from hydromodpy.cli.conventions import (
        HmpParser,
        add_workspace_before_the_verb,
        install_old_cli_forms,
    )

    prog = Path(sys.argv[0]).stem if sys.argv[0] else "hmp"
    parser = HmpParser(
        prog=prog,
        description="HydroModPy command-line interface",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=_version_string(),
        help="Print version and exit",
    )
    add_workspace_before_the_verb(parser)
    subparsers = parser.add_subparsers(
        dest="command", metavar="<command>", required=True, help="Available commands"
    )
    for mod in ALL_COMMANDS:
        mod.register(subparsers)
    install_old_cli_forms(parser)
    return parser


def _enable_argcomplete(parser: argparse.ArgumentParser) -> None:
    """Wire shell completion via argcomplete when the dep is installed.

    Activation requires ``register-python-argcomplete hmp`` in the user's
    shell. The optional import keeps argcomplete a soft dependency.
    """
    try:
        import argcomplete
    except ImportError:
        return
    argcomplete.autocomplete(parser)


def main(argv: list[str] | None = None) -> None:
    """Parse ``argv`` and dispatch to the matching subcommand.

    Unhandled exceptions raised by a subcommand handler are routed through
    :func:`hydromodpy.cli.helpers.exit_code_for` so the shell sees the right
    typed exit code, with the ``HMPY.Exxx`` of the failure first on the line
    stderr gets. ``SystemExit`` propagates unchanged.

    SIGTERM is turned into an exception for the whole process, before the
    parser is even built. Every scheduler stop, every container stop and every
    plain ``kill`` sends it, and the default handler ends the process where it
    stands: the ``finally`` that closes a session, or writes the outcome of a
    canceled job, never runs. Installed here rather than around one verb
    because building the parser imports every command module, which is seconds
    of real work that a signal arriving in the meantime used to throw away
    without a trace.
    """
    from hydromodpy.core.runtime.interrupts import terminate_as_interrupt

    with terminate_as_interrupt():
        _dispatch(argv)


def _dispatch(argv: list[str] | None) -> None:
    """Build the parser, parse *argv* and run the handler it names."""
    from hydromodpy.cli.conventions import WORKSPACE_ROOT_DEST
    from hydromodpy.cli.output import stdout_for_a_program

    parser = _build_parser()
    _enable_argcomplete(parser)
    args = parser.parse_args(argv)

    handler = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help(sys.stderr)
        sys.exit(EXIT_USAGE)
    # Named after the verb too, the last one on the line wins, as a repeated flag does.
    args.workspace = getattr(args, "workspace", None) or getattr(args, WORKSPACE_ROOT_DEST)

    from hydromodpy.core.io.proj_bootstrap import bootstrap_proj
    from hydromodpy.core.runtime.bootstrap_hook import ensure_bootstrapped

    ensure_bootstrapped()
    bootstrap_proj()
    with stdout_for_a_program(args):
        try:
            handler(args)
        except SystemExit:
            raise
        except BaseException as exc:
            fail(exc)


if __name__ == "__main__":
    main()
