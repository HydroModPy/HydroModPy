"""``hmp catalog reindex`` - rebuild the project index from the run directories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hydromodpy.cli._conventions import format_parser, workspace_parser
from hydromodpy.cli.helpers import exit_code_for
from hydromodpy.core.state.paths import resolve_project_root

NAME: str = "reindex"
HELP: str = "Rebuild the project index from what the run directories declare"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser()],
        description=(
            "Read every sealed run under runs/ and rebuild .hmp/index.duckdb from it. "
            "The current index stays readable until the new one is published in one "
            "atomic step, and rebuilding twice yields the same index. What no run "
            "directory carries is not rebuilt: audit history, tags, notes, export log "
            "and calibration sessions."
        ),
        epilog="Example:\n  hmp catalog reindex",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import reindex_project

    project_root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        report = reindex_project(project_root)
    except Exception as exc:  # noqa: BLE001 - map rebuild errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    if args.format == "json":
        print(json.dumps(report))
        return
    if args.format == "csv":
        print("run,state,detail")
        for name in report["indexed"]:
            print(f"{name},indexed,")
        for item in report["skipped"]:
            print(f"{item['run']},skipped,{item['reason']}")
        return

    print(f"index: {report['index']}")
    print(f"indexed {len(report['indexed'])} run(s)")
    for name in report["indexed"]:
        print(f"  {name}")
    for table, count in sorted(report["rows"].items()):
        print(f"  {table}: {count} row(s)")
    for item in report["skipped"]:
        print(f"  skipped {item['run']}: {item['reason']}", file=sys.stderr)
