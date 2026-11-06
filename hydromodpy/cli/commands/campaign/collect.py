"""``hmp campaign collect`` - write ``summary/`` of a project from its runs.

A thin wrapper of :func:`hydromodpy.project.launch.summary.collect_project`: the
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

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.output import emit

NAME: str = "collect"
HELP: str = "Write summary/ of a project: tables by case and by site, map, figures, exports"

_EPILOG = """\
Examples:
  hmp campaign collect
  hmp campaign collect projects/bretagne_k --write-sites
  hmp campaign collect . --mixed-windows
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=None,
        help="Project directory, or a folder inside it (default: -w, else the current directory)",
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
    from hydromodpy.core.state.result_dirs import resolve_project_root
    from hydromodpy.project.launch.summary import collect_project

    project_root = resolve_project_root(
        Path(args.project or args.workspace or ".").expanduser().resolve()
    )
    paths = collect_project(
        project_root, write_sites=args.write_sites, mixed_windows=args.mixed_windows
    )
    summary = paths.readme.parent

    def table() -> None:
        print(f"wrote {summary}")
        for path in (paths.by_case, paths.by_site, paths.catalog, paths.report, paths.readme):
            if path is not None:
                print(f"  {path.relative_to(summary).as_posix()}")

    # A figure that could not be drawn says so whatever the format.
    for line in paths.skipped:
        print(f"figure not drawn: {line}", file=sys.stderr)
    emit(
        args,
        "campaign collect",
        {
            "summary": summary,
            "by_case": paths.by_case,
            "by_site": paths.by_site,
            "catalog": paths.catalog,
            "report": paths.report,
            "readme": paths.readme,
            "figures_not_drawn": list(paths.skipped),
        },
        table=table,
    )
