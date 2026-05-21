"""``hmp dev run-script`` - run a Python prototype script outside ``hmp run``."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_NOT_FOUND

NAME: str = "run-script"
HELP: str = "Run a Python prototype script outside the stable hmp run contract"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("script", type=Path, help="Path to a Python script")
    parser.add_argument(
        "script_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to the Python script",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.display.banner import print_hydromodpy

    script_path = Path(args.script).expanduser().resolve()
    if not script_path.is_file():
        print(f"File not found: {script_path}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    print_hydromodpy()
    cmd = [sys.executable, str(script_path), *list(args.script_args)]
    result = subprocess.run(cmd, cwd=str(script_path.parent))
    sys.exit(result.returncode)
