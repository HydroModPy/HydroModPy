"""``hmp catalog reindex`` - build the project index from the run directories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import apply_verbosity, exit_code_for
from hydromodpy.core.state.paths import resolve_project_root

NAME: str = "reindex"
HELP: str = "Build the project index from what the run and session directories declare"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        description=(
            "Read every directory under runs/ and sessions/ and write .hmp/index.duckdb from "
            "them: the sealed runs with their label of the day, the attempts that failed or "
            "are running, the calibration sessions with their trials. The index is written "
            "to a staging file and published in one atomic step, so a reader keeps reading "
            "until the new one is there, and building twice yields the same index. With "
            "--incremental only the directories that appeared, changed or disappeared since "
            "the last pass are written."
        ),
        epilog="Examples:\n  hmp catalog reindex\n  hmp catalog reindex --incremental",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Write only what changed since the last pass; a full rebuild otherwise",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.cli._workers.catalog import reindex_project

    project_root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        report = reindex_project(project_root, incremental=args.incremental)
    except Exception as exc:  # noqa: BLE001 - map indexing errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    if args.format == "json":
        print(json.dumps(report))
        return
    if args.format == "csv":
        print("rel_dir,state,detail")
        for name in report["indexed"]:
            print(f"{name},indexed,")
        for name in report["sessions"]:
            print(f"{name},indexed_session,")
        for name in report["removed"]:
            print(f"{name},removed,")
        for item in report["skipped"]:
            print(f"{item['rel_dir']},skipped,{item['reason']}")
        return

    print(f"index: {report['index']}")
    mode = "rebuilt" if report["full"] else "refreshed"
    print(
        f"{mode}: {len(report['indexed'])} run(s), {len(report['sessions'])} session(s), "
        f"{len(report['removed'])} removed"
    )
    for name in report["indexed"]:
        print(f"  {name}")
    for name in report["sessions"]:
        print(f"  {name}")
    for name in report["removed"]:
        print(f"  removed {name}")
    for table, count in sorted(report["rows"].items()):
        print(f"  {table}: {count} row(s)")
    for item in report["skipped"]:
        print(f"  skipped {item['rel_dir']}: {item['reason']}", file=sys.stderr)
