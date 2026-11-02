"""``hmp project case``: the case file one task of a scheduler job runs."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.conventions import verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_USAGE, apply_verbosity, exit_code_for

NAME: str = "case"
HELP: str = "Print the case file of task N of a job (jobs/<job>/cases.txt, task 1 first)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[verbosity_parser(), workspace_parser()],
        epilog="Example:\n  hmp project case 20261020-143000-slurm 3 -w .",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("job", help="Folder under jobs/, or its path")
    parser.add_argument("task", type=int, help="Task number, 1 for the first line of cases.txt")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.cli._workers.project import sites_project_root
    from hydromodpy.project.launch.journal import case_for_task

    try:
        root = sites_project_root(args.workspace or ".")
        path = case_for_task(root, args.job, int(args.task))
    except IndexError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_USAGE)
    except Exception as exc:  # noqa: BLE001 - map errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    print(path)
