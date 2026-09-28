"""``hmp export`` - write data of a run to files, the words of an ``[[export]]`` block.

A thin wrapper of :func:`hydromodpy.export`: the positionals say what
(``head watertable_depth``, ``discharge``, ``watershed``, or ``all``),
``--time`` or ``--period`` when, ``--folder`` or ``--file`` where. The format
follows the data unless ``--format`` or the extension of ``--file`` names one.
``--list`` prints what the run can export, by kind.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import add_sim_ref, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_USAGE, apply_verbosity, exit_code_for

NAME: str = "export"
HELP: str = "Export data of a run: fields, series, layers, the budget, or the whole run"

# The values of ExportFormat, written out so that building the parser imports
# no config model. A test keeps the two lists equal.
FORMAT_CHOICES: tuple[str, ...] = (
    "netcdf",
    "geotiff",
    "csv",
    "geopackage",
    "shapefile",
    "vtu",
    "package",
    "stac",
    "rocrate",
    "prov",
)

_EPILOG = """\
Examples:
  hmp export nancon_step5_export --list
  hmp export nancon_step5_export all
  hmp export nancon_step5_export head watertable_depth --time 2002-10-15
  hmp export nancon_step5_export discharge discharge_obs --period 2001-01-01 2002-12-31
  hmp export nancon_step5_export watershed hydrographic_network_reference
  hmp export nancon_step5_export watertable_depth --time last --file nappe.tif --crs EPSG:4326
  hmp export nancon_step5_export all --format package
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), verbosity_parser()],
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser)
    parser.add_argument(
        "variables",
        nargs="*",
        metavar="VARIABLE",
        help=(
            'What to export: names from --list, or "all" for everything the run holds, '
            "each in its natural format"
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print what this run can export, by kind, and write nothing",
    )
    parser.add_argument(
        "--time",
        nargs="+",
        default=None,
        metavar="TIME",
        help=(
            'Instants to write: dates (2002-10-15), "first" or "last". A date takes the '
            "stress period that holds it. Default: the whole simulation"
        ),
    )
    parser.add_argument(
        "--period",
        nargs=2,
        default=None,
        metavar=("START", "END"),
        help="A window of the simulation, two dates. Every period it overlaps is written",
    )
    parser.add_argument(
        "--format",
        choices=FORMAT_CHOICES,
        default=None,
        help="File format. Default: the natural format of each data, or the --file extension",
    )
    parser.add_argument(
        "--folder",
        default=None,
        help="Folder to write into, with automatic names (default: share/<run>/)",
    )
    parser.add_argument(
        "--file",
        default=None,
        help="One exact file; its extension gives the format",
    )
    parser.add_argument(
        "--crs",
        default=None,
        help="Output CRS of rasters and vector layers, e.g. EPSG:4326 (default: the model CRS)",
    )
    parser.add_argument(
        "--resolution",
        type=float,
        default=None,
        help="Pixel size of a GeoTIFF, in units of the output CRS (default: from the mesh)",
    )
    parser.add_argument(
        "--layer",
        type=int,
        default=None,
        help="Model layer of a field of several layers (0 is the top one)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    import hydromodpy as hmp
    from hydromodpy.core.state.paths import resolve_project_root

    workspace = resolve_project_root(Path(args.workspace or Path.cwd()).expanduser().resolve())
    if not args.list and not args.variables:
        print(
            "Name what to export (see --list), or write 'all'. "
            "Example: hmp export <run> head --time 2002-10-15",
            file=sys.stderr,
        )
        sys.exit(EXIT_USAGE)
    try:
        if args.list:
            _print_list(hmp, workspace, args.sim_ref)
            return
        with hmp.open(workspace, read_only=False) as catalog:
            written = hmp.export(
                catalog[args.sim_ref],
                args.variables[0] if len(args.variables) == 1 else list(args.variables),
                time=_time_argument(args.time),
                period=tuple(args.period) if args.period else None,
                format=args.format,
                folder=args.folder,
                file=args.file,
                crs=args.crs,
                resolution=args.resolution,
                layer=args.layer,
            )
    except Exception as exc:  # noqa: BLE001 - mapped to a typed exit code below
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    for path in written:
        print(path)
    print(f"Exported {len(written)} file(s)", file=sys.stderr)


def _time_argument(values: list[str] | None) -> str | int | list[str | int] | None:
    """Return ``--time`` as the request reads it: one instant, or a list."""
    if not values:
        return None
    instants: list[str | int] = [
        int(value) if value.lstrip("-").isdigit() else value for value in values
    ]
    return instants[0] if len(instants) == 1 else instants


def _print_list(hmp: object, workspace: Path, sim_ref: str) -> None:
    """Print what one run can export, grouped by kind."""
    from hydromodpy.results.exporters.vocabulary import describe_exportable, list_exportable

    with hmp.open(workspace) as catalog:  # type: ignore[attr-defined]
        run = catalog[sim_ref]
        names = list_exportable(run)
        label = run.name or run.sim_id[:8]
    print(f"{label} can export:")
    print(describe_exportable(names))
