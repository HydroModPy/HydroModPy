"""``hmp catalog point`` - read a variable in one precise cell of a finished run.

Thin wrapper around :func:`hydromodpy.cli._workers.catalog.point_simulations`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import format_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, exit_code_for
from hydromodpy.core.state.paths import resolve_project_root

NAME: str = "point"
HELP: str = "Read a variable in one cell of a finished run (coordinates, cell id, or depth)"

EPILOG = """Examples:
  hmp catalog point @last --var head --xy 395100 6824925
  hmp catalog point @last --var head --cell 5000 --timestep -1
  hmp catalog point @last --var head --xy 395100 6824925 --depth 12.5
  hmp catalog point run_a run_b --var watertable_depth --cell 5000 -o point.csv
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser()],
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
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="Write the table to a .csv or .parquet file",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import point_simulations
    from hydromodpy.results.catalog import (
        AmbiguousReferenceError,
        SimulationNotFoundError,
    )
    from hydromodpy.results.errors import FieldNotFoundError
    from hydromodpy.results.run.point import PointOutsideMeshError

    workspace_root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    x, y = args.xy if args.xy else (None, None)
    try:
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
            output=args.output,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except (AmbiguousReferenceError, SimulationNotFoundError, FieldNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    except (PointOutsideMeshError, IndexError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    if frame.empty:
        print("(no value at this point)")
        return

    if args.format == "json":
        print(frame.to_json(orient="records", date_format="iso", indent=2))
    elif args.format == "csv":
        print(frame.to_csv(index=False), end="")
    else:
        print(frame.to_string(index=False))

    if args.output:
        print(f"written: {args.output}")
