"""``hmp data get`` - thin wrapper around :func:`hydromodpy.fetch_data_variable`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_CONFIG

NAME: str = "get"
HELP: str = "Fetch an upstream variable and write a JSON sidecar next to the file"


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = value.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "bbox must be 'minx,miny,maxx,maxy' (four comma-separated floats)"
        )
    try:
        floats = tuple(float(p) for p in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"bbox values must be floats ({exc})") from exc
    return (floats[0], floats[1], floats[2], floats[3])


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("variable", help="Variable name (e.g. dem, piezometry, hydrometry)")
    parser.add_argument(
        "--bbox",
        default=None,
        type=_parse_bbox,
        metavar="MINX,MINY,MAXX,MAXY",
        help=(
            "Bounding box minx,miny,maxx,maxy in the workspace CRS. "
            "When minx is negative, use '--bbox=-1.17,48.4,-1.0,48.5' (= sign)."
        ),
    )
    parser.add_argument("--workspace", default=None)
    parser.add_argument(
        "--source", default="upstream", help="Free-form label recorded in the sidecar"
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    import hydromodpy as hmp

    try:
        result = hmp.fetch_data_variable(
            args.variable, bbox=args.bbox, workspace=args.workspace, source=args.source
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    print(f"  Fetched {args.variable} -> {result['target']}")
    print(f"  Sidecar  -> {result['sidecar']}")
