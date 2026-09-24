"""``hmp data get`` - serve a data request into a folder.

Two forms, one engine (:func:`hydromodpy.data.run_request`):

- ``hmp data get request.json --out DIR``: the request document;
- ``hmp data get <variable> --bbox ... --crs ... --out DIR``: one variable,
  built from the options.

``DIR`` receives one file per variable and source, cut to the extent and the
period, and the report ``request.json``.
"""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli._conventions import verbosity_parser
from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_VALIDATION, apply_verbosity, exit_code_for
from hydromodpy.core import progress

NAME: str = "get"
HELP: str = "Serve a data request: one file per variable, cut to the extent and period"


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
    parser = subparsers.add_parser(NAME, help=HELP, parents=[verbosity_parser()])
    parser.add_argument(
        "target",
        metavar="REQUEST_OR_VARIABLE",
        help="a request document (.json) or a variable name (e.g. dem, hydrometry)",
    )
    parser.add_argument("--out", required=True, help="folder that receives the files")
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument(
        "--bbox",
        default=None,
        type=_parse_bbox,
        metavar="MINX,MINY,MAXX,MAXY",
        help=(
            "box in the CRS --crs names. When minx is negative, write "
            "'--bbox=-1.17,48.4,-1.0,48.5' (= sign)."
        ),
    )
    selector.add_argument("--mask", default=None, help="vector file bounding the request")
    selector.add_argument(
        "--stations", default=None, help="comma-separated station codes, for station variables"
    )
    parser.add_argument("--crs", default=None, help="CRS of --bbox, as EPSG:<code>")
    parser.add_argument("--start", default=None, help="first date of the period (YYYY-MM-DD)")
    parser.add_argument(
        "--end", default=None, help="last date of the period, kept whole (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--source", default=None, help="source to ask, when the variable has several"
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help="workspace whose data cache is read and filled (default: an in-memory cache)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.cli._workers.data import request_data

    stations = [code.strip() for code in args.stations.split(",")] if args.stations else None
    try:
        with progress.status(f"Serving {args.target}"):
            report = request_data(
                args.target,
                out=args.out,
                bbox=args.bbox,
                crs=args.crs,
                mask=args.mask,
                stations=stations,
                start=args.start,
                end=args.end,
                source=args.source,
                workspace=args.workspace,
            )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except Exception as exc:  # noqa: BLE001 - mapped to its typed exit code
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(exit_code_for(exc))

    for item in report["files"]:
        where = "empty" if item["empty"] else item["path"]
        print(f"  {item['variable']:<16} {item['source']:<24} {where}")
    for failure in report["failures"]:
        print(
            f"  {failure['variable']:<16} {failure['source'] or '':<24} FAILED: {failure['error']}",
            file=sys.stderr,
        )
    print(f"  Report -> {args.out}/request.json")
    if report["failures"]:
        sys.exit(EXIT_VALIDATION)
