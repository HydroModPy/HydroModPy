"""``hmp project collect`` - write ``summary/`` of a project from its runs.

A thin wrapper of :func:`hydromodpy.project.summary.collect_project`: the
index is brought up to date, then ``summary/`` gets the tables by case and by
site, the map, the cohort figures, the exports of ``[[sites.export]]``, a page
and a README. ``--write-sites`` adds ``summary/catalog.csv``, the sites as a
site table; ``--mixed-windows`` ranks scores of different windows together.
A cohort figure that cannot be drawn is named on stderr.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import verbosity_parser
from hydromodpy.cli.helpers import apply_verbosity, exit_code_for

NAME: str = "collect"
HELP: str = "Write summary/ of a project: tables by case and by site, map, figures, exports"

_EPILOG = """\
Examples:
  hmp project collect
  hmp project collect projects/bretagne_k --write-sites
  hmp project collect . --mixed-windows
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[verbosity_parser()],
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=".",
        help="Project directory, or a folder inside it (default: the current directory)",
    )
    parser.add_argument(
        "--write-sites",
        action="store_true",
        help="Also write summary/catalog.csv, the sites as a site table (SiteRow columns)",
    )
    parser.add_argument(
        "--mixed-windows",
        action="store_true",
        help="Rank scores computed on different windows or rules together",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.core.state.paths import resolve_project_root
    from hydromodpy.project.summary import collect_project

    project_root = resolve_project_root(Path(args.project).expanduser().resolve())
    try:
        paths = collect_project(
            project_root, write_sites=args.write_sites, mixed_windows=args.mixed_windows
        )
    except Exception as exc:  # noqa: BLE001 - every failure leaves with its typed exit code
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    summary = paths.readme.parent
    print(f"wrote {summary}")
    for path in (paths.by_case, paths.by_site, paths.catalog, paths.report, paths.readme):
        if path is not None:
            print(f"  {path.relative_to(summary).as_posix()}")
    for line in paths.skipped:
        print(f"figure not drawn: {line}", file=sys.stderr)
