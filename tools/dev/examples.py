"""``python -m tools.dev examples manifest``: regenerate the shipped example catalog."""

from __future__ import annotations

import argparse
from pathlib import Path

from hydromodpy.cli.conventions import add_destination
from hydromodpy.cli.helpers import EXIT_CONFIG, exit_code_for, refuse
from hydromodpy.core.exceptions import HydroModPyError
from hydromodpy.project.examples.generate import write_catalog
from hydromodpy.project.examples.rows import summary

NAME: str = "examples"
HELP: str = "Regenerate hydromodpy/project/examples/catalog.toml from this checkout"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="examples_command")

    manifest_p = sub.add_parser(
        "manifest",
        help="Rewrite the example catalog",
        epilog="Example:\n  python -m tools.dev examples manifest --root . --to catalog.toml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    manifest_p.add_argument("--root", default=None, help="Checkout root (default: auto-detect)")
    add_destination(manifest_p, help="Destination (default: the wheel copy)", metavar="FILE")

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    if getattr(args, "examples_command", None) != "manifest":
        refuse(
            "usage: python -m tools.dev examples manifest [--root PATH] [--to FILE]", EXIT_CONFIG
        )

    try:
        written, catalog = write_catalog(
            root=Path(args.root) if args.root else None,
            destination=Path(args.to) if args.to else None,
        )
        entries = [summary(entry) for entry in catalog]
    except (HydroModPyError, OSError) as exc:
        refuse(f"[dev examples] {exc}", exit_code_for(exc), cause=exc)

    print(f"[dev examples] Wrote {written}")
    for entry in entries:
        print(
            f"  {entry['id']}  {entry['file_count']} file(s), "
            f"{entry['total_size']} bytes  {entry['directory']}"
        )
