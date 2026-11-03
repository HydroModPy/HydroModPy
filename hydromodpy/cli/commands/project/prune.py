"""``hmp project prune`` - trash the kept trials of a session, all but the best.

Thin wrapper over :func:`hydromodpy.calibration.runners.promotion.prune_session`.
Each trial directory moves to ``trash/``, from which ``hmp catalog restore``
brings it back; ``hmp catalog gc`` frees the bytes later.
"""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.conventions import confirm_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_SIGINT, EXIT_USAGE, apply_verbosity, resolve_project

NAME: str = "prune"
HELP: str = "Move the kept trials of a calibration session to the trash, all but the best"

KEEP_POLICIES: tuple[str, ...] = ("best",)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), confirm_parser(), verbosity_parser()],
        epilog=(
            "Examples:\n"
            "  hmp project prune calibration --keep best -y\n"
            "  hmp project prune J0014010-calage -w projects/bretagne -y"
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
    from hydromodpy.calibration.runners.promotion import prune_session
    from hydromodpy.core.state.paths import catalog_path_for

    project_root = resolve_project(args.workspace)
    if not args.yes:
        if not sys.stdin.isatty():
            print("Refusing to prune without -y in non-interactive mode.", file=sys.stderr)
            sys.exit(EXIT_USAGE)
        try:
            resp = input(
                f"Move the kept trials of {args.case} to the trash, all but the {args.keep}? [y/N] "
            )
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            sys.exit(EXIT_SIGINT)
        if resp.strip().lower() not in {"y", "yes"}:
            print("Aborted.", file=sys.stderr)
            sys.exit(EXIT_SIGINT)

    moved = prune_session(project_root, args.case, keep=args.keep)
    if moved and catalog_path_for(project_root).is_file():
        from hydromodpy.results.catalog.indexer import index_new_runs

        index_new_runs(project_root)
    if not moved:
        print(f"no kept trial to prune in {args.case}")
        return
    print(f"moved {len(moved)} trial(s) of {args.case} to trash/:")
    for path in moved:
        print(f"  {path.name}")
    print("Restore one: hmp catalog restore <name above>")
