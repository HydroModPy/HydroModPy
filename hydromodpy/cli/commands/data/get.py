"""``hmp data get`` - serve a data request into a folder.

Two forms, one engine (:func:`hydromodpy.data.run_request`):

- ``hmp data get request.json --to DIR``: the request document;
- ``hmp data get <variable> --bbox ... --crs ... --to DIR``: one variable,
  built from the options.

``DIR`` receives one file per variable and source, cut to the extent and the
period, and the report ``request.json``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.conventions import (
    add_destination,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_VALIDATION,
    exit_code_for,
    refuse,
    resolve_workspace,
)
from hydromodpy.cli.output import emit
from hydromodpy.core.console import progress

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
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog="Examples:\n  hmp data get dem --to data/dem --bbox 340000,6780000,350000,6790000 --crs EPSG:2154\n  hmp data get precipitation --to data/precipitation --mask catchment.gpkg --start 2015-01-01 --end 2020-12-31 --source sim2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "target",
        metavar="REQUEST_OR_VARIABLE",
        help="a request document (.json) or a variable name (e.g. dem, hydrometry)",
    )
    add_destination(parser, help="folder that receives the files", required=True, metavar="DIR")
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
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.data.request.cache_verbs import request_data

    workspace_root = resolve_workspace(args.workspace) if args.workspace is not None else None
    stations = [code.strip() for code in args.stations.split(",")] if args.stations else None
    try:
        with progress.status(f"Serving {args.target}"):
            report = request_data(
                args.target,
                out=args.to,
                bbox=args.bbox,
                crs=args.crs,
                mask=args.mask,
                stations=stations,
                start=args.start,
                end=args.end,
                source=args.source,
                workspace_root=workspace_root,
            )
    except ValueError as exc:
        refuse(str(exc), EXIT_CONFIG, cause=exc)
    except Exception as exc:  # noqa: BLE001 - mapped to its typed exit code
        refuse(f"{type(exc).__name__}: {exc}", exit_code_for(exc), cause=exc)

    written = Path(args.to) / "request.json"

    def table() -> None:
        for item in report["files"]:
            where = "empty" if item["empty"] else item["path"]
            print(f"  {item['variable']:<16} {item['source']:<24} {where}")
        print(f"  Report -> {written}")

    for failure in report["failures"]:
        print(
            f"  {failure['variable']:<16} {failure['source'] or '':<24} FAILED: {failure['error']}",
            file=sys.stderr,
        )
    emit(
        args,
        "data get",
        {"files": report["files"], "failures": report["failures"], "report": written},
        table=table,
    )
    if report["failures"]:
        sys.exit(EXIT_VALIDATION)
