"""``hmp site import``: declare sites from a table, a layer or Hub'Eau."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.conventions import workspace_parser
from hydromodpy.cli.helpers import EXIT_USAGE, exit_code_for

NAME: str = "import"
HELP: str = "Declare sites from a table, a vector layer or Hub'Eau stations"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser()],
        epilog=(
            "Examples:\n"
            "  hmp site import stations.csv --tag bretagne\n"
            "  hmp site import --hubeau --bbox 150000 6700000 420000 6900000 --min-years 10\n"
            "  hmp site import --layer exutoires.gpkg --name-field code --gauge-field station"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "table",
        nargs="?",
        type=Path,
        default=None,
        help="CSV site table in the columns site, label, gauge, uri, x_outlet, y_outlet, crs, tags",
    )
    source = parser.add_argument_group("source (one of the table, --hubeau, --layer)")
    source.add_argument(
        "--hubeau", action="store_true", help="Hub'Eau discharge stations inside --bbox"
    )
    source.add_argument("--layer", type=Path, default=None, help="Vector layer of outlet points")
    hubeau = parser.add_argument_group("--hubeau")
    hubeau.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("XMIN", "YMIN", "XMAX", "YMAX"),
        default=None,
        help="Box searched, in --crs",
    )
    hubeau.add_argument(
        "--crs", default="EPSG:2154", help="CRS of the box and of the outlets (default: EPSG:2154)"
    )
    hubeau.add_argument(
        "--min-years",
        type=float,
        default=None,
        help="Keep stations open at least this many years (opening to closing, or today)",
    )
    hubeau.add_argument(
        "--snap-network",
        default=None,
        help="Snap each outlet onto this river network: a vector file, or bdtopage",
    )
    hubeau.add_argument(
        "--snap-max-m",
        type=float,
        default=200.0,
        help="Farthest snap in metres; a station farther away is skipped (default: 200)",
    )
    layer = parser.add_argument_group("--layer")
    layer.add_argument("--name-field", default=None, help="Field holding the site name")
    layer.add_argument("--gauge-field", default=None, help="Field holding the station code")
    layer.add_argument("--label-field", default=None, help="Field holding the readable name")
    layer.add_argument("--layer-name", default=None, help="Layer of a multi-layer file")
    parser.add_argument(
        "--tag", action="append", default=[], help="Tag added to every site; repeat for several"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace sites of the same name and accept outlets close to other sites",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the sites read without writing the catalog"
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli.helpers import resolve_workspace
    from hydromodpy.data.sites.catalog import catalog_path, declare_sites, with_tags

    chosen = [
        name
        for name, given in (
            ("a table", args.table is not None),
            ("--hubeau", args.hubeau),
            ("--layer", args.layer is not None),
        )
        if given
    ]
    if len(chosen) != 1:
        print(
            "hmp site import reads exactly one source: a table, --hubeau or --layer "
            f"(given: {', '.join(chosen) or 'none'}).",
            file=sys.stderr,
        )
        sys.exit(EXIT_USAGE)
    if args.hubeau and args.bbox is None:
        print("--hubeau needs --bbox XMIN YMIN XMAX YMAX.", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    if args.layer is not None and args.name_field is None:
        print("--layer needs --name-field, the field holding the site name.", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    root = resolve_workspace(args.workspace)
    try:
        imported = _read(args, root)
        rows = [with_tags(row, args.tag) for row in imported.rows]
        for reason in imported.skipped:
            print(f"[skipped] {reason}", file=sys.stderr)
        if args.dry_run:
            for row in rows:
                print(_line(row))
            print(f"{len(rows)} site(s) read, nothing written (--dry-run)")
            return
        declare_sites(root, rows, force=args.force)
    except Exception as exc:  # noqa: BLE001 - map errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    print(f"[written] {len(rows)} site(s): {catalog_path(root)}")


def _read(args: argparse.Namespace, root: Path):
    from hydromodpy.data.sites.importers import (
        rows_from_hubeau,
        rows_from_layer,
        rows_from_table,
    )

    if args.table is not None:
        return rows_from_table(args.table)
    if args.layer is not None:
        return rows_from_layer(
            args.layer,
            name_field=args.name_field,
            gauge_field=args.gauge_field,
            label_field=args.label_field,
            layer=args.layer_name,
        )
    return rows_from_hubeau(
        args.bbox,
        crs=args.crs,
        min_years=args.min_years,
        snap_network=args.snap_network,
        snap_max_m=args.snap_max_m,
        snap_output_dir=root / "data" / "hydrography",
    )


def _line(row) -> str:
    outlet = "" if row.x_outlet is None else f" outlet=({row.x_outlet:.1f}, {row.y_outlet:.1f})"
    gauge = "" if row.gauge is None else f" gauge={row.gauge}"
    return f"{row.site}{gauge}{outlet}"
