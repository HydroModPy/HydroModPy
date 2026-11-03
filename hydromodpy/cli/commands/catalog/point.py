"""``hmp catalog point`` - read a variable in one precise cell of a finished run.

Thin wrapper around :func:`hydromodpy.cli._workers.catalog.point_simulations`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from hydromodpy.cli.conventions import (
    add_destination,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import apply_verbosity
from hydromodpy.cli.output import emit
from hydromodpy.core.state.paths import resolve_project_root

NAME: str = "point"
HELP: str = "Read a variable in one cell of a finished run (coordinates, cell id, or depth)"

EPILOG = """Examples:
  hmp catalog point @last --var head --xy 395100 6824925
  hmp catalog point @last --var head --cell 5000 --timestep -1
  hmp catalog point @last --var head --xy 395100 6824925 --depth 12.5
  hmp catalog point run_a run_b --var watertable_depth --cell 5000 --to point.csv
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "sim_ref",
        metavar="SIM_REF",
        nargs="+",
        help=(
            "One or more runs (full sim_id, unique hex prefix, name, or an "
            "@-selector). Several runs stack their answers for comparison."
        ),
    )
    parser.add_argument(
        "--var",
        dest="variables",
        metavar="NAME",
        action="append",
        required=True,
        help="Field to read, persisted or virtual. Repeat for several fields.",
    )
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument(
        "--xy",
        nargs=2,
        type=float,
        metavar=("X", "Y"),
        help="Coordinates in the simulation CRS",
    )
    where.add_argument("--cell", type=int, help="Zero-based cell index")
    vertical = parser.add_mutually_exclusive_group()
    vertical.add_argument("--layer", type=int, help="Zero-based layer index")
    vertical.add_argument(
        "--depth",
        type=float,
        metavar="METRES",
        help="Depth below the local model top; picks the layer",
    )
    parser.add_argument("--label", help="Name of the point reported in the table")
    parser.add_argument(
        "--timestep",
        type=int,
        help="Keep a single timestep (negative counts from the end)",
    )
    add_destination(parser, help="Write the table to a .csv or .parquet file", metavar="FILE")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.cli._workers.catalog import point_simulations

    workspace_root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    x, y = args.xy if args.xy else (None, None)
    frame = point_simulations(
        list(args.sim_ref),
        workspace=workspace_root,
        variables=list(args.variables),
        x=x,
        y=y,
        cell=args.cell,
        layer=args.layer,
        depth=args.depth,
        label=args.label,
        timestep=args.timestep,
        output=args.to,
    )

    def table() -> None:
        print("(no value at this point)" if frame.empty else frame.to_string(index=False))
        if args.to:
            print(f"written: {args.to}")

    emit(args, "catalog point", frame, table=table)
