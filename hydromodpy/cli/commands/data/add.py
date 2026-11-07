"""``hmp data add`` - thin wrapper around :func:`hydromodpy.add_data_entry`.

``--workspace`` names the data cache the file lands in. ``--frozen`` compares
the file against ``hydromodpy.lock``, which lives at a project root: that is
what ``--project`` names, so the check works from outside a project too.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, refuse
from hydromodpy.cli.output import emit

NAME: str = "add"
HELP: str = "Power-user command to ingest a single file with explicit metadata"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog="Example:\n  hmp data add dem.tif --type dem --crs EPSG:2154 --unit m",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("file", help="Path to the source file to ingest")
    parser.add_argument("--type", dest="variable", default=None, help="Variable name")
    parser.add_argument("--provider", default="custom", help="Provider label")
    parser.add_argument("--crs", default=None, help="EPSG code (e.g. EPSG:2154)")
    parser.add_argument("--unit", default=None, help="Override unit")
    parser.add_argument(
        "--station-id",
        default=None,
        dest="station_id",
        help="Station the file belongs to (default: the file name without its extension)",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project root owning hydromodpy.lock (--frozen only; defaults to the current one)",
    )
    parser.add_argument(
        "--frozen", action="store_true", help="Refuse to ingest if lockfile has no matching entry"
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli.helpers import resolve_workspace
    from hydromodpy.data.request.cache_verbs import add_data_entry

    if not args.variable:
        refuse("--type is required (e.g. --type piezometry)", EXIT_CONFIG)

    try:
        result = add_data_entry(
            args.file,
            variable=args.variable,
            provider=args.provider,
            crs=args.crs,
            unit=args.unit,
            station_id=args.station_id,
            workspace_root=resolve_workspace(args.workspace),
            project=args.project,
            frozen=args.frozen,
        )
    except FileNotFoundError as exc:
        refuse(str(exc), EXIT_NOT_FOUND, cause=exc)
    except ValueError as exc:
        refuse(str(exc), EXIT_CONFIG, cause=exc)

    label = result["station_id"] or "(no station)"
    emit(
        args,
        "data add",
        result,
        table=lambda: print(
            f"  Added: {result['variable']}/{result['provider']}/{label} -> {result['dest']}"
        ),
    )
