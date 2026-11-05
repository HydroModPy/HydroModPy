"""``hmp project import``: install a package written by ``hmp publish --package``.

A thin wrapper of :func:`hydromodpy.project.exchange.install.import_project`: the
project lands as ``projects/<name>`` of the workspace, its data under
``data/`` with the rules of ``hmp catalog import`` (identical bytes cost
nothing, other bytes at the same path are refused by name, nothing written),
and its runs are indexed.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from hydromodpy.cli.conventions import (
    dry_run_parser,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import apply_verbosity, resolve_workspace
from hydromodpy.cli.output import emit

NAME: str = "import"
HELP: str = "Install a package written by 'hmp publish --package' as a project of the workspace"

_EPILOG = """\
Examples:
  hmp project import my_catchment.tar -w ~/hydromodpy
  hmp project import my_catchment.tar -w ~/hydromodpy --name my_catchment_from_lab
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), dry_run_parser(), format_parser(), verbosity_parser()],
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("source", help="The package: a .tar file or a folder")
    parser.add_argument(
        "--name",
        default=None,
        help="Name of the project (default: the name it was exported under)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.project.exchange.install import import_project
    from hydromodpy.results.catalog.indexer import index_new_runs

    workspace = resolve_workspace(args.workspace)
    imported = import_project(Path(args.source), workspace, name=args.name, dry_run=args.dry_run)
    if imported.runs and not args.dry_run:
        index_new_runs(imported.project_dir)
    report = imported.install

    def table() -> None:
        verb = "would import" if args.dry_run else "imported"
        print(f"{verb} {args.source} as {imported.project_dir}")
        print(
            f"files: {len(report.written)} written, {len(report.unchanged)} already there, "
            f"{len(report.stations_written)} station row(s), "
            f"{len(report.cache_registered)} data cache row(s), {len(report.sites_added)} site(s)"
        )
        print(
            f"runs: {len(imported.runs)}, sessions: {len(imported.sessions)}, "
            f"mesh cache entries: {len(imported.mesh_entries)}"
        )
        if not args.dry_run:
            print(f"next: hmp project show {imported.project_dir.name} -w {workspace}")

    emit(
        args,
        "project import",
        {
            "applied": not args.dry_run,
            "project": imported.project_dir.name,
            "path": imported.project_dir,
            "written": list(report.written),
            "unchanged": list(report.unchanged),
            "runs": list(imported.runs),
            "sessions": list(imported.sessions),
            "mesh_entries": list(imported.mesh_entries),
        },
        table=table,
    )
