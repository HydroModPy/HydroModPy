"""Top-level CLI dispatcher for HydroModPy.

Builds the argparse tree from :mod:`hydromodpy.cli.commands` and invokes
the subcommand handler attached via ``parser.set_defaults(_handler=...)``.
Unhandled exceptions are mapped to typed exit codes by
:func:`hydromodpy.cli.helpers.exit_code_for` so the shell sees a meaningful
status (POSIX-conventional 130 for SIGINT, 10..19 for specific failure
categories).
"""

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_OK, exit_code_for


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

    prog = Path(sys.argv[0]).stem if sys.argv[0] else "hmp"
    parser = argparse.ArgumentParser(
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
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    for mod in ALL_COMMANDS:
        mod.register(subparsers)
    return parser


def main(argv: list[str] | None = None) -> None:
    """Parse ``argv`` and dispatch to the matching subcommand.

    Unhandled exceptions raised by a subcommand handler are routed through
    :func:`hydromodpy.cli.helpers.exit_code_for` so the shell sees the right
    typed exit code. ``SystemExit`` propagates unchanged.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    handler = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help()
        sys.exit(EXIT_OK)
    try:
        handler(args)
    except SystemExit:
        raise
    except BaseException as exc:
        message = str(exc) or type(exc).__name__
        print(message, file=sys.stderr)
        sys.exit(exit_code_for(exc))


if __name__ == "__main__":
    main()
