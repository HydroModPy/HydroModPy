"""``hmp export-package`` - emit a portable ``.hmp`` archive for a simulation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_GENERIC, EXIT_NOT_FOUND, EXIT_OK
from hydromodpy.core.state.paths import catalog_path_for

NAME: str = "export-package"
HELP: str = "Export a simulation as a portable .hmp archive (tar.zst with RO-Crate manifest)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "sim_ref",
        help="Simulation reference: full UUID, UUID prefix (>=4 chars), or name",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        type=Path,
        help="Destination .hmp file path",
    )
    parser.add_argument(
        "-w",
        "--workspace",
        default=None,
        help="Workspace root containing the catalog (default: cwd)",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project name (used when sim_ref is a simulation name)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog import (
        AmbiguousReferenceError,
        Catalog,
        SimulationNotFoundError,
    )

    workspace_root = Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    db_path = catalog_path_for(workspace_root)
    if not db_path.exists():
        print(f"No catalog found at {workspace_root}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with Catalog(workspace_root) as catalog:
        try:
            sim_id = catalog.resolve(args.sim_ref, project=args.project)
        except (AmbiguousReferenceError, SimulationNotFoundError) as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        try:
            produced = catalog.export_package(sim_id, output_path)
        except Exception as exc:
            print(f"Export failed: {exc}", file=sys.stderr)
            sys.exit(EXIT_GENERIC)

    print(str(produced))
    sys.exit(EXIT_OK)
