"""``hmp campaign case``: the case file one task of a scheduler job runs."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_USAGE, refuse
from hydromodpy.cli.output import emit

NAME: str = "case"
HELP: str = "Print the case file of task N of a job (jobs/<job>/cases.txt, task 1 first)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[format_parser(), verbosity_parser(), workspace_parser()],
        epilog="Example:\n  hmp campaign case 20261020-143000-slurm 3 -w .",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("job", help="Folder under jobs/, or its path")
    parser.add_argument("task", type=int, help="Task number, 1 for the first line of cases.txt")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.core.state.result_dirs import sites_project_root
    from hydromodpy.project.launch.journal import case_for_task

    try:
        root = sites_project_root(args.workspace or ".")
        path = case_for_task(root, args.job, int(args.task))
    except IndexError as exc:
        refuse(str(exc), EXIT_USAGE, cause=exc)
    emit(args, "campaign case", {"path": path}, table=lambda: print(path))
