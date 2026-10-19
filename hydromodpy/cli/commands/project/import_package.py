"""``hmp project import``: install a package written by ``hmp project export``.

A thin wrapper of :func:`hydromodpy.catalog.install.import_project`: the
project lands as ``projects/<name>`` of the workspace, its data under
``data/`` with the rules of ``hmp catalog import`` (identical bytes cost
nothing, other bytes at the same path are refused by name, nothing written),
and its runs are indexed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import apply_verbosity, exit_code_for, resolve_workspace

NAME: str = "import"
HELP: str = "Install a package written by 'hmp project export' as a project of the workspace"

_EPILOG = """\
Examples:
  hmp project import my_catchment.tar -w ~/hydromodpy
  hmp project import my_catchment.tar -w ~/hydromodpy --as my_catchment_from_lab
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), verbosity_parser()],
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("source", help="The package: a .tar file or a folder")
    parser.add_argument(
        "--as",
        dest="as_name",
        default=None,
        help="Name of the project (default: the name it was exported under)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.catalog.install import import_project
    from hydromodpy.results.catalog.indexer import index_new_runs

    workspace = resolve_workspace(args.workspace)
    try:
        imported = import_project(Path(args.source), workspace, name=args.as_name)
    except Exception as exc:  # noqa: BLE001 - mapped to a typed exit code below
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    if imported.runs:
        index_new_runs(imported.project_dir)
    report = imported.install
    print(f"imported {args.source} as {imported.project_dir}")
    print(
        f"files: {len(report.written)} written, {len(report.unchanged)} already there, "
        f"{len(report.stations_written)} station row(s), "
        f"{len(report.cache_registered)} data cache row(s), {len(report.sites_added)} site(s)"
    )
    print(
        f"runs: {len(imported.runs)}, sessions: {len(imported.sessions)}, "
        f"mesh cache entries: {len(imported.mesh_entries)}"
    )
    print(f"next: hmp project show {imported.project_dir.name} -w {workspace}")
