"""``hmp init`` — scaffold a HydroModPy workspace."""

from __future__ import annotations

import argparse


NAME = "init"
HELP = "Create HydroModPy workspace (data + projects). Default: ~/hydromodpy/"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "--path", default=None, help="Workspace path (default: ~/hydromodpy/)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.data.scaffold import scaffold

    result = scaffold(args.path)

    print(f"Workspace: {result}")
    print()
    print("Structure:")
    for p in sorted(result.rglob("*")):
        rel = p.relative_to(result)
        indent = "  " * len(rel.parts)
        if p.is_dir():
            print(f"  {indent}{rel.name}/")
        else:
            print(f"  {indent}{rel.name}")
    print()
    print("Next steps:")
    print("  1. Drop your files into <variable>_custom/ folders (see README.md there)")
    print("  2. Run: hmp data check to validate them before first run")
    print("  3. Run: hmp new <project_name>")
    print("  4. Edit projects/<project>/project.toml with your settings")
