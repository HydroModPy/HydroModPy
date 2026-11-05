"""``hmp catalog reindex`` - build the project index from the run directories."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import apply_verbosity
from hydromodpy.cli.output import emit
from hydromodpy.core.state.result_dirs import resolve_project_root

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
    report = reindex_project(project_root, incremental=args.incremental)

    def table() -> None:
        print(f"index: {report['index']}")
        mode = "rebuilt" if report["full"] else "refreshed"
        print(
            f"{mode}: {len(report['indexed'])} run(s), {len(report['sessions'])} session(s), "
            f"{len(report['removed'])} removed"
        )
        for name in [*report["indexed"], *report["sessions"]]:
            print(f"  {name}")
        for name in report["removed"]:
            print(f"  removed {name}")
        for name, count in sorted(report["rows"].items()):
            print(f"  {name}: {count} row(s)")
        for item in report["skipped"]:
            print(f"  skipped {item['rel_dir']}: {item['reason']}", file=sys.stderr)

    states = (("indexed", "indexed"), ("sessions", "indexed_session"), ("removed", "removed"))
    rows = [
        {"rel_dir": name, "state": state, "detail": ""}
        for key, state in states
        for name in report[key]
    ]
    rows += [
        {"rel_dir": item["rel_dir"], "state": "skipped", "detail": item["reason"]}
        for item in report["skipped"]
    ]
    emit(args, "catalog reindex", report, table=table, csv=(("rel_dir", "state", "detail"), rows))
