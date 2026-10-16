"""``hmp site add``: declare one site in the catalog of the workspace."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli._conventions import workspace_parser
from hydromodpy.cli.helpers import EXIT_CONFIG, exit_code_for

NAME: str = "add"
HELP: str = "Declare one site in data/sites/catalog.csv"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser()],
        epilog=(
            "Example:\n  hmp site add couesnon --outlet 377120 6831410 "
            "--gauge J017000001 --uri hubeau:J0170000"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("name", help="Site name: letters, digits and underscores")
    parser.add_argument(
        "--outlet",
        nargs=2,
        type=float,
        metavar=("X", "Y"),
        default=None,
        help="Outlet coordinates in --crs",
    )
    parser.add_argument("--crs", default="EPSG:2154", help="CRS of the outlet (default: EPSG:2154)")
    parser.add_argument("--label", default=None, help="Readable name of the catchment")
    parser.add_argument("--gauge", default=None, help="Station that measures the catchment")
    parser.add_argument("--uri", default=None, help="hubeau:<code> or bdtopage:<code>")
    parser.add_argument(
        "--tag", action="append", default=[], help="Tag of the site; repeat for several"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace a site of the same name and accept an outlet close to another site",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli.commands.site._workspace import workspace_root
    from hydromodpy.core.site import SiteRow
    from hydromodpy.data.sites.catalog import catalog_path, declare_sites

    root = workspace_root(args.workspace)
    x, y = args.outlet if args.outlet is not None else (None, None)
    try:
        row = SiteRow(
            site=args.name,
            label=args.label,
            gauge=args.gauge,
            uri=args.uri,
            x_outlet=x,
            y_outlet=y,
            crs=args.crs if args.outlet is not None else None,
            tags=tuple(dict.fromkeys(args.tag)),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    try:
        declare_sites(root, [row], force=args.force)
    except Exception as exc:  # noqa: BLE001 - map errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    print(f"[written] site {row.site}: {catalog_path(root)}")
