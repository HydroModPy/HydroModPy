"""``hmp campaign prune`` - trash the kept trials of a session, all but the best.

Thin wrapper over :func:`hydromodpy.calibration.runners.promotion.prune_session`.
Each trial directory moves to ``trash/``, from which ``hmp catalog restore``
brings it back; ``hmp catalog gc`` frees the bytes later.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import (
    confirm_parser,
    dry_run_parser,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import apply_verbosity, confirm, resolve_project
from hydromodpy.cli.output import emit

NAME: str = "prune"
HELP: str = "Move the kept trials of a calibration session to the trash, all but the best"

KEEP_POLICIES: tuple[str, ...] = ("best",)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[
            workspace_parser(),
            confirm_parser(),
            dry_run_parser(),
            format_parser(),
            verbosity_parser(),
        ],
        epilog=(
            "Examples:\n"
            "  hmp campaign prune calibration --keep best -y\n"
            "  hmp campaign prune calibration --dry-run\n"
            "  hmp campaign prune J0014010-calage -w projects/bretagne -y"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("case", help="Case of the session, <case> or <case>.vN")
    parser.add_argument(
        "--keep",
        choices=KEEP_POLICIES,
        default="best",
        help="Trials left in place (default: best, the trial session.json points at)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.calibration.runners.promotion import prune_session, trials_to_prune
    from hydromodpy.core.state.paths import catalog_path_for

    project_root = resolve_project(args.workspace)
    if args.dry_run:
        names = [path.name for path in trials_to_prune(project_root, args.case, keep=args.keep)]
        emit(
            args,
            "campaign prune",
            {"case": args.case, "applied": False, "trials": names},
            table=lambda: print(f"would move {len(names)} trial(s) of {args.case} to trash/"),
        )
        return
    confirm(
        args,
        f"Move the kept trials of {args.case} to the trash, all but the {args.keep}?",
        doing="prune",
    )

    moved = prune_session(project_root, args.case, keep=args.keep)
    if moved and catalog_path_for(project_root).is_file():
        from hydromodpy.results.catalog.indexer import index_new_runs

        index_new_runs(project_root)

    def table() -> None:
        if not moved:
            print(f"no kept trial to prune in {args.case}")
            return
        print(f"moved {len(moved)} trial(s) of {args.case} to trash/:")
        for path in moved:
            print(f"  {path.name}")
        print("Restore one: hmp catalog restore <name above>")

    emit(
        args,
        "campaign prune",
        {"case": args.case, "applied": True, "trials": [path.name for path in moved]},
        table=table,
    )
