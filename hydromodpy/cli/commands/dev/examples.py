"""``hmp dev examples manifest`` - regenerate the shipped example catalog."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_CONFIG, exit_code_for
from hydromodpy.core.exceptions import HydroModPyError

NAME: str = "examples"
HELP: str = "Regenerate hydromodpy/examples/catalog.toml from this checkout"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="examples_command")

    manifest_p = sub.add_parser("manifest", help="Rewrite the example catalog")
    manifest_p.add_argument("--root", default=None, help="Checkout root (default: auto-detect)")
    manifest_p.add_argument("--output", default=None, help="Destination (default: the wheel copy)")

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from pathlib import Path

    from hydromodpy.cli._workers.example import generate_manifest

    if getattr(args, "examples_command", None) != "manifest":
        print("usage: hmp dev examples manifest [--root PATH] [--output PATH]", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    try:
        written, entries = generate_manifest(
            root=Path(args.root) if args.root else None,
            destination=Path(args.output) if args.output else None,
        )
    except (HydroModPyError, OSError) as exc:
        print(f"[dev examples] {exc}", file=sys.stderr)
        sys.exit(exit_code_for(exc))

    print(f"[dev examples] Wrote {written}")
    for entry in entries:
        print(
            f"  {entry['id']}  {entry['file_count']} file(s), "
            f"{entry['total_size']} bytes  {entry['directory']}"
        )
