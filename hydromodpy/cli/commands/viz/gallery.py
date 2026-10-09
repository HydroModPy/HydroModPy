"""``hmp viz gallery`` - thin wrapper around :func:`hydromodpy.render_gallery`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli._conventions import verbosity_parser
from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, apply_verbosity
from hydromodpy.core import progress

NAME: str = "gallery"
HELP: str = "Render the [display] figure gallery for one or several runs"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[verbosity_parser()],
        epilog="Examples:\n  hmp viz gallery run.toml --latest 1\n  hmp viz gallery run.toml --run my_run --only flux_timeseries,water_budget",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("config", help="Path to a project TOML file")
    parser.add_argument(
        "--run",
        dest="run_name",
        default=None,
        metavar="NAME",
        help="Render every run of this name (default: the newest run of the config)",
    )
    parser.add_argument(
        "--sim",
        dest="sim_ref",
        default=None,
        metavar="UUID",
        help="Render one run, by id, unique prefix, name or @-selector",
    )
    parser.add_argument(
        "--all", action="store_true", dest="all_runs", help="Render every run of the config"
    )
    parser.add_argument(
        "--latest",
        type=int,
        default=None,
        metavar="N",
        help="Render the N newest runs of the config",
    )
    parser.add_argument(
        "--only",
        default=None,
        metavar="FIG1,FIG2",
        help="Render only these figures, by name (default: those of [display].figures)",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        dest="no_show",
        help="Do not open the figures in a window",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.cli._workers.viz import render_gallery

    only = [s.strip() for s in args.only.split(",") if s.strip()] if args.only else None
    try:
        with progress.status("Rendering gallery figures"):
            paths = render_gallery(
                args.config,
                run_name=args.run_name,
                sim_ref=args.sim_ref,
                all_runs=args.all_runs,
                latest=args.latest,
                only=only,
                no_show=args.no_show,
            )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    for path in paths:
        print(f"  wrote {path}", file=sys.stderr)
