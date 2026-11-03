"""``hmp export`` - write data of a run to files, the words of an ``[[export]]`` block.

A thin wrapper of :func:`hydromodpy.export`: the positionals say what
(``head watertable_depth``, ``discharge``, ``watershed``, or ``all``),
``--time`` or ``--period`` when, ``--to`` where under ``runs/<run>/exports/``:
a name with an extension is one file, any other a folder. The file format
follows the data unless ``--as`` or the extension of ``--to`` names one.
``--format`` is what the command prints, as on every verb. ``--list`` prints
what the run can export, by kind; ``--regen`` writes again what the ledgers of
the run record, its exports, its figures or both. A copy out of the project is
``hmp publish``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.conventions import (
    add_destination,
    add_sim_ref,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import (
    EXIT_GENERIC,
    EXIT_USAGE,
    apply_verbosity,
    project_root_of,
    refuse,
)
from hydromodpy.cli.output import emit

NAME: str = "export"
HELP: str = "Export data of a run: fields, series, layers, the budget, or the whole run"

# The values of ExportFormat, written out so that building the parser imports
# no config model. A test keeps the two lists equal.
FILE_FORMATS: tuple[str, ...] = (
    "netcdf",
    "geotiff",
    "csv",
    "geopackage",
    "shapefile",
    "vtu",
    "stac",
    "rocrate",
    "prov",
)

REGEN_CHOICES: tuple[str, ...] = ("all", "exports", "figures")

_EPILOG = """\
Examples:
  hmp export my_run --list
  hmp export my_run all
  hmp export my_run head watertable_depth --time 2002-10-15
  hmp export my_run discharge discharge_obs --period 2001-01-01 2002-12-31
  hmp export my_run watershed hydrographic_network_reference
  hmp export my_run watertable_depth --time last --to watertable.tif --crs EPSG:4326
  hmp export my_run head --to maps/ --as geotiff
  hmp export my_run --regen
  hmp export my_run --regen figures
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[
            workspace_parser(),
            format_parser(not_for="The file format of an export is --as."),
            verbosity_parser(),
        ],
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
        "--regen",
        nargs="?",
        const="all",
        choices=REGEN_CHOICES,
        default=None,
        help=(
            "Write again what the run recorded: its exports (exports/index.json), its "
            "figures (figures/index.json), or both, the default"
        ),
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
        "--as",
        dest="file_format",
        choices=FILE_FORMATS,
        default=None,
        help="File format. Default: the natural format of each data, or the --to extension",
    )
    add_destination(
        parser,
        help=(
            "Where under runs/<run>/exports/: a name with an extension is one exact file, and "
            "gives the format; any other is a folder, with automatic names "
            "(default: runs/<run>/exports/)"
        ),
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
        help="Pixel size of a GeoTIFF, in units of the output CRS (default: the side of the smallest cell)",
    )
    parser.add_argument(
        "--layer",
        type=int,
        default=None,
        help="Model layer of a field of several layers (0 is the top one)",
    )
    parser.add_argument(
        "--nodata",
        type=float,
        default=None,
        help="Fill value of the cells a GeoTIFF has no data for (default: -9999)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    import hydromodpy as hmp

    workspace = project_root_of(args)
    if args.regen and (args.list or args.variables):
        refuse("--regen writes again what the ledgers record: name no variable.", EXIT_USAGE)
    if not args.list and not args.regen and not args.variables:
        refuse(
            "Name what to export (see --list), or write 'all'. "
            "Example: hmp export <run> head --time 2002-10-15",
            EXIT_USAGE,
        )
    if args.list:
        _print_list(args, hmp, workspace)
        return
    if args.regen:
        written = _regen(hmp, workspace, args.sim_ref, args.regen)
    else:
        folder, file = _destination(args.to)
        with hmp.open(workspace).store as catalog:
            written = hmp.export(
                catalog[args.sim_ref],
                args.variables[0] if len(args.variables) == 1 else list(args.variables),
                time=_time_argument(args.time),
                period=tuple(args.period) if args.period else None,
                format=args.file_format,
                folder=folder,
                file=file,
                crs=args.crs,
                resolution=args.resolution,
                layer=args.layer,
                **({} if args.nodata is None else {"nodata": args.nodata}),
            )

    def table() -> None:
        for path in written:
            print(path)
        again = " again" if args.regen else ""
        print(f"Exported {len(written)} file(s){again}", file=sys.stderr)

    emit(args, "export", {"files": written, "regenerated": args.regen}, table=table)


def _destination(to: str | None) -> tuple[str | None, str | None]:
    """Read ``--to`` as the folder or the file of an export: an extension makes it a file."""
    if to is None:
        return None, None
    if to.endswith("/") or not Path(to).suffix:
        return to, None
    return None, to


def _time_argument(values: list[str] | None) -> str | int | list[str | int] | None:
    """Return ``--time`` as the request reads it: one instant, or a list."""
    if not values:
        return None
    instants: list[str | int] = [
        int(value) if value.lstrip("-").isdigit() else value for value in values
    ]
    return instants[0] if len(instants) == 1 else instants


def _regen(hmp: object, workspace: Path, sim_ref: str, what: str) -> list[Path]:
    """Write again what the ledgers of one run record: exports, figures or both.

    ``all`` writes what each ledger holds. It stops only on a run with nothing recorded.
    """
    from hydromodpy.cli._workers.viz import regen_figures
    from hydromodpy.results.exporters.request import regen_exports, run_export_target
    from hydromodpy.results.ledger import Ledger
    from hydromodpy.results.storage.contract import RUN_EXPORTS_DIRNAME, RUN_FIGURES_DIRNAME

    with hmp.open(workspace).store as catalog:  # type: ignore[attr-defined]
        sid = catalog.resolve(sim_ref)
        run_dir = Path(catalog.run_dir_for(sid))
        holds = {
            name: bool(Ledger.read(run_dir / folder).entries)
            for name, folder in (("exports", RUN_EXPORTS_DIRNAME), ("figures", RUN_FIGURES_DIRNAME))
        }
        if what == "all" and not any(holds.values()):
            refuse(f"{run_dir.name} records no export and no figure to write again.", EXIT_GENERIC)
        written: list[Path] = []
        if what == "exports" or (what == "all" and holds["exports"]):
            written += regen_exports(catalog, sid, run_export_target(catalog, sid))
    if what == "figures" or (what == "all" and holds["figures"]):
        written += regen_figures(sim_ref, workspace=workspace)
    return written


def _print_list(args: argparse.Namespace, hmp: object, workspace: Path) -> None:
    """Say what one run can export, grouped by kind."""
    from hydromodpy.results.exporters.vocabulary import describe_exportable, list_exportable

    with hmp.open(workspace).store as catalog:  # type: ignore[attr-defined]
        run = catalog[args.sim_ref]
        names = list_exportable(run)
        label = run.name or run.sim_id[:8]

    def table() -> None:
        print(f"{label} can export:")
        print(describe_exportable(names))

    emit(
        args,
        "export list",
        [{"name": name, "kind": kind} for name, kind in sorted(names.items())],
        table=table,
    )
