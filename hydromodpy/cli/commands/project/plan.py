"""``hmp project plan``: expand a ``[sites]`` project and write ``plan/<hash>/``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_CONFIG, apply_verbosity, fail
from hydromodpy.cli.output import emit

NAME: str = "plan"
HELP: str = "Write the plan of a [sites] project: every site crossed with every recipe"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[format_parser(), verbosity_parser(), workspace_parser()],
        epilog=(
            "Examples:\n  hmp project plan .\n  hmp project plan . --recipe calage.toml\n"
            "  hmp project plan . --set flow.param.K.field.value=2e-5"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=None,
        help="Project folder or its project.toml (default: -w, else the current directory)",
    )
    parser.add_argument(
        "--recipe",
        type=Path,
        default=None,
        metavar="FILE",
        help="Plan one recipe file alone on every site, instead of project.toml",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        dest="set_overrides",
        metavar="PATH=VALUE",
        help="Dotted override rendered into every case. Repeatable.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Go past the running case: write the plan while a case of the current plan runs",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.cli._workers.project import sites_project_root
    from hydromodpy.config.sites.issues import PlanError, group_issues
    from hydromodpy.core.exceptions import HydroModPyError
    from hydromodpy.core.toml_io.overrides import set_overrides
    from hydromodpy.project.launch import plan_project
    from hydromodpy.results.plan_store import current_plan_hash, plan_path

    try:
        root = sites_project_root(args.project or args.workspace or ".")
        draft = plan_project(
            root,
            config_path=None if args.recipe is None else Path(args.recipe),
            set_overrides=set_overrides(list(args.set_overrides)),
            env=os.environ,
            force=bool(args.force),
        )
    except PlanError as exc:
        for line in exc.lines:
            print(f"error: {line}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except (HydroModPyError, FileNotFoundError, ValueError) as exc:
        fail(exc)
    for line in group_issues(draft.warnings):
        print(f"warning: {line}", file=sys.stderr)
    plan_hash = current_plan_hash(root)
    n_sealed = sum(1 for case in draft.cases if case.done)
    path = None if plan_hash is None else plan_path(root, plan_hash)

    def table() -> None:
        print(
            f"plan {plan_hash}: {len(draft.cases)} cases ({len(draft.sites)} sites x "
            f"{len(draft.recipes)} recipes), {n_sealed} already sealed"
        )
        if path is not None:
            print(f"  {path}")

    emit(
        args,
        "project plan",
        {
            "plan_hash": plan_hash,
            "path": path,
            "n_cases": len(draft.cases),
            "n_sites": len(draft.sites),
            "n_recipes": len(draft.recipes),
            "n_sealed": n_sealed,
        },
        table=table,
    )
