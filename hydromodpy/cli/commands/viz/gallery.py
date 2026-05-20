"""``hmp viz gallery`` - thin wrapper around :func:`hydromodpy.render_gallery`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND

NAME: str = "gallery"
HELP: str = "Render the [display] figure gallery for one or several runs"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("config", help="Path to a project TOML file")
    parser.add_argument("--run", dest="run_name", default=None, metavar="NAME")
    parser.add_argument("--sim", dest="sim_ref", default=None, metavar="UUID")
    parser.add_argument("--all", action="store_true", dest="all_runs")
    parser.add_argument("--latest", type=int, default=None, metavar="N")
    parser.add_argument("--only", default=None, metavar="FIG1,FIG2")
    parser.add_argument("--no-show", action="store_true", dest="no_show")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.viz import render_gallery

    only = [s.strip() for s in args.only.split(",") if s.strip()] if args.only else None
    try:
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
