"""``hmp project status``: where each case of the current plan stands, read from the disk."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.output import emit

NAME: str = "status"
HELP: str = "Show where each case of the current plan stands (outcome.json, heartbeat)"

COLUMNS: tuple[str, ...] = (
    "case_id",
    "site",
    "recipe",
    "status",
    "rel_dir",
    "attempt",
    "step",
    "started_at",
    "ended_at",
    "host",
    "pid",
    "error",
)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[format_parser(), verbosity_parser(), workspace_parser()],
        epilog="Examples:\n  hmp project status .\n  hmp project status . --format csv",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=None,
        help="Project folder or its project.toml (default: -w, else the current directory)",
    )
    parser.add_argument(
        "--stale-minutes",
        type=float,
        default=None,
        metavar="MIN",
        help="Age of the pulse past which a running case reads as stale (default: 5)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.project import sites_project_root
    from hydromodpy.project.launch import project_status
    from hydromodpy.results.outcome import DEFAULT_STALE_AFTER_S

    stale_after_s = (
        DEFAULT_STALE_AFTER_S if args.stale_minutes is None else 60.0 * args.stale_minutes
    )
    report = project_status(
        sites_project_root(args.project or args.workspace or "."), stale_after_s=stale_after_s
    )
    records = [{column: _cell(getattr(row, column)) for column in COLUMNS} for row in report.rows]

    def table() -> None:
        counts = ", ".join(f"{n} {status}" for status, n in report.counts().items()) or "no case"
        stale = " (the project files changed since: plan again)" if report.plan_stale else ""
        print(f"plan {report.plan_hash}{stale}: {counts}")
        shown = ("case_id", "status", "rel_dir", "step", "host", "pid", "error")
        rows = [[record[column] for column in shown] for record in records]
        widths = [
            max(len(column), *(len(line[i]) for line in rows)) for i, column in enumerate(shown)
        ]
        for line in [list(shown), *rows]:
            print(
                "  ".join(
                    cell.ljust(width) for cell, width in zip(line, widths, strict=True)
                ).rstrip()
            )

    emit(
        args,
        "project status",
        {
            "plan_hash": report.plan_hash,
            "plan_stale": report.plan_stale,
            "counts": report.counts(),
            "cases": records,
        },
        table=table,
        csv=(COLUMNS, records),
    )


def _cell(value: object) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat(timespec="seconds")
    return str(value)
