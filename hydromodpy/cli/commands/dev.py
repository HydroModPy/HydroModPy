"""Developer-only CLI helpers."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_NOT_FOUND

NAME: str = "dev"
HELP: str = "Run developer-only commands"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    commands = parser.add_subparsers(dest="dev_command", required=True)

    script = commands.add_parser(
        "run-script",
        help="Run a Python prototype script outside the stable hmp run contract",
    )
    script.add_argument("script", type=Path, help="Path to a Python script")
    script.add_argument(
        "script_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to the Python script",
    )
    script.set_defaults(_handler=run_script)
    return parser


def run(args: argparse.Namespace) -> None:
    """Dispatch a developer command."""
    handler = getattr(args, "_handler", None)
    if handler is None:
        raise SystemExit(2)
    handler(args)


def run_script(args: argparse.Namespace) -> None:
    """Run a Python prototype script as a subprocess."""
    from hydromodpy.display.banner import print_hydromodpy

    script_path = Path(args.script).expanduser().resolve()
    if not script_path.is_file():
        print(f"File not found: {script_path}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    print_hydromodpy()
    cmd = [sys.executable, str(script_path), *list(args.script_args)]
    result = subprocess.run(cmd, cwd=str(script_path.parent))
    sys.exit(result.returncode)
