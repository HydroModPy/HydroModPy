"""``hmp dev examples manifest`` - regenerate the shipped example catalog."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import add_destination, workspace_parser
from hydromodpy.cli.helpers import EXIT_CONFIG, exit_code_for, refuse
from hydromodpy.core.exceptions import HydroModPyError

NAME: str = "examples"
HELP: str = "Regenerate hydromodpy/examples/catalog.toml from this checkout"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="examples_command")

    manifest_p = sub.add_parser(
        "manifest",
        help="Rewrite the example catalog",
        parents=[workspace_parser(reads_none=True)],
        epilog="Example:\n  hmp dev examples manifest --root examples --to manifest.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    manifest_p.add_argument("--root", default=None, help="Checkout root (default: auto-detect)")
    add_destination(manifest_p, help="Destination (default: the wheel copy)", metavar="FILE")

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from pathlib import Path

    from hydromodpy.cli._workers.example import generate_manifest

    if getattr(args, "examples_command", None) != "manifest":
        refuse("usage: hmp dev examples manifest [--root PATH] [--to FILE]", EXIT_CONFIG)

    try:
        written, entries = generate_manifest(
            root=Path(args.root) if args.root else None,
            destination=Path(args.to) if args.to else None,
        )
    except (HydroModPyError, OSError) as exc:
        refuse(f"[dev examples] {exc}", exit_code_for(exc), cause=exc)

    print(f"[dev examples] Wrote {written}")
    for entry in entries:
        print(
            f"  {entry['id']}  {entry['file_count']} file(s), "
            f"{entry['total_size']} bytes  {entry['directory']}"
        )
