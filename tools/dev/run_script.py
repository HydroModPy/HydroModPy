"""``python -m tools.dev run-script``: run a Python prototype script with the banner."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from hydromodpy.cli.banner import print_hydromodpy
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, refuse
from hydromodpy.core.logging import current_verbosity

NAME: str = "run-script"
HELP: str = "Run a Python prototype script, from the folder of the script"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        epilog="Example:\n  python -m tools.dev run-script prototype.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("script", type=Path, help="Path to a Python script")
    parser.add_argument(
        "script_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to the Python script",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    script_path = Path(args.script).expanduser().resolve()
    if not script_path.is_file():
        refuse(f"File not found: {script_path}", EXIT_NOT_FOUND)
    if current_verbosity() != "quiet":
        print_hydromodpy()
    cmd = [sys.executable, str(script_path), *list(args.script_args)]
    result = subprocess.run(cmd, cwd=str(script_path.parent))
    sys.exit(result.returncode)
