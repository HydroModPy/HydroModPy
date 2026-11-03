"""``hmp catalog import`` - bring a run published by ``hmp publish`` into the project.

A thin wrapper of :func:`hydromodpy.project.install.import_run`: the run lands
under ``runs/`` and is indexed, and a copy published ``--with inputs`` installs
every file it read into the ``data/`` of the workspace, with its station rows,
its data cache rows and its site. The command ends with the two commands that
replay the run and compare the replay with it.
"""

from __future__ import annotations

import argparse
import shlex
from pathlib import Path

from hydromodpy.cli.conventions import (
    dry_run_parser,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import apply_verbosity, project_root_of
from hydromodpy.cli.output import emit

NAME: str = "import"
HELP: str = "Import a run written by 'hmp publish' (directory or tar), with the data it read"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), dry_run_parser(), format_parser(), verbosity_parser()],
        epilog=(
            "The run lands under runs/ with the next free version of its name,\n"
            "read without its .vN: a published x.v2 becomes x in a project that has\n"
            "no x. Pass --name to give it the name other documents cite.\n"
            "\n"
            "A copy published with --with inputs installs every file the run read\n"
            "into data/ of the workspace: identical bytes already there cost nothing,\n"
            "other bytes at the same path are refused by name, and nothing is written.\n"
            "\n"
            "Examples:\n"
            "  hmp catalog import baseline.tar\n"
            "  hmp catalog import ../published/baseline --name lab_copy"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("source", help="Directory or tar written by 'hmp publish'")
    parser.add_argument(
        "--name",
        default=None,
        help="Name of the imported run (default: the published name without its .vN)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.project.install import import_run

    root = project_root_of(args)
    imported = import_run(root, Path(args.source), name=args.name, dry_run=args.dry_run)
    if not args.dry_run:
        # Like ``hmp run``: the import builds the index when the project has none yet.
        from hydromodpy.results.catalog.indexer import index_new_runs

        index_new_runs(root)
    report = imported.install
    following = _next_commands(root, imported.rel_dir, workspace=args.workspace)

    def table() -> None:
        verb = "would import" if args.dry_run else "imported"
        print(f"{verb} {args.source} as {imported.rel_dir}")
        if report is None:
            print("The copy carries no inputs: a rerun reads data/ of this workspace.")
        else:
            print(
                f"data: {len(report.written)} file(s) written, {len(report.unchanged)} already "
                f"there, {len(report.stations_written)} station row(s), "
                f"{len(report.cache_registered)} data cache row(s), "
                f"{len(report.sites_added)} site(s)"
            )
            for dest in report.written:
                print(f"  + {dest}")
        if not args.dry_run:
            print("next:")
            for line in following:
                print(f"  {line}")

    emit(
        args,
        "catalog import",
        {
            "applied": not args.dry_run,
            "rel_dir": imported.rel_dir,
            "name": Path(imported.rel_dir).name,
            "written": [] if report is None else list(report.written),
            "unchanged": [] if report is None else list(report.unchanged),
            "next": following,
        },
        table=table,
    )


def _next_commands(root: Path, rel_dir: str, *, workspace: str | None) -> list[str]:
    """Return the rerun of the imported run and the comparison of the two."""
    from hydromodpy.core.state.paths import parse_rel_dir
    from hydromodpy.results.catalog.registration import next_version_dirname, split_stem_version

    name = parse_rel_dir(rel_dir).name
    replay = next_version_dirname(root, split_stem_version(name)[0])
    where = f" -w {shlex.quote(str(root))}" if workspace else ""
    return [f"hmp catalog rerun {name}{where}", f"hmp catalog diff {name} {replay}{where}"]
