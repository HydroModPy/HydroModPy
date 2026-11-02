"""``hmp project export``: a whole project with its data, in one package.

A thin wrapper of
:func:`hydromodpy.results.export.project_package.export_project`: the files the
author wrote, every data file the TOML files reference with its station rows,
and on demand the sealed runs, the sessions, the consumed mesh cache entries
and the files a provider delivered. ``hmp project import`` installs it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.conventions import verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import apply_verbosity, exit_code_for, resolve_project_ref

NAME: str = "export"
HELP: str = "Write a project with its data in one package, which 'hmp project import' installs"

_EPILOG = """\
Examples:
  hmp project export my_catchment --to my_catchment.tar
  hmp project export . --to my_catchment.tar --with runs --with mesh --with fetched
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), verbosity_parser()],
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=None,
        help=(
            "A project name under projects/, or a path ('.', a/b) to a project "
            "(default: the project of -w or of the cwd)"
        ),
    )
    parser.add_argument("--to", required=True, help="The package: a .tar file, or a new folder")
    parser.add_argument(
        "--format",
        choices=("tar", "dir"),
        default="tar",
        help="Write a tar archive (default) or a directory",
    )
    parser.add_argument(
        "--with",
        dest="with_",
        action="append",
        choices=("runs", "sessions", "mesh", "fetched"),
        default=[],
        help=(
            "Take along 'runs' (the sealed runs with their results), 'sessions', 'mesh' (the "
            "mesh cache entries the runs read) or 'fetched' (the files a provider delivered "
            "to the runs); repeatable"
        ),
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.catalog.share import inputs_of
    from hydromodpy.results.export.project_package import export_project

    project = resolve_project_ref(args.workspace, args.project)
    try:
        written = export_project(
            project,
            Path(args.to).expanduser(),
            format=args.format,
            with_=tuple(args.with_),
            bundle_of=inputs_of(project),
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a typed exit code below
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    print(written)
    print(
        f"Install it elsewhere with: hmp project import {written} -w <workspace>", file=sys.stderr
    )
