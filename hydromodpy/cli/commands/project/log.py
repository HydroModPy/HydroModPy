"""``hmp project log``: the journal of the latest launch, or its failed cases."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.output import emit, output_of

NAME: str = "log"
HELP: str = "Print the journal of the latest launch (--failed: one line per failed case)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[format_parser(), verbosity_parser(), workspace_parser()],
        epilog=(
            "Examples:\n  hmp project log .\n  hmp project log . --failed\n"
            "  hmp project log . --job 20261020-143000-slurm"
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
        "--failed",
        action="store_true",
        help="Only the last end of every case that failed, aborted or went stale",
    )
    parser.add_argument(
        "--job",
        default=None,
        metavar="JOB",
        help="A folder under jobs/ (default: the latest launch)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.core.state.result_dirs import sites_project_root
    from hydromodpy.project.launch.journal import read_journal

    events = read_journal(
        sites_project_root(args.project or args.workspace or "."),
        failed_only=bool(args.failed),
        job=args.job,
    )

    def table() -> None:
        if not events:
            print("no failed case" if args.failed else "no launch journal")
        for event in events:
            print(_line(event))

    emit(
        args,
        "project log",
        events,
        table=table,
        csv=(CSV_COLUMNS, [_csv_row(event) for event in events]),
    )


CSV_COLUMNS: tuple[str, ...] = tuple(
    field for field in output_of("project log").fields if field != "log_tail"
)
"""Columns of ``--format csv``: one row per event; fields an event lacks stay empty."""


def _csv_row(event: dict) -> dict:
    """Return one event as one row, the error as one ``type: message`` cell."""
    error = event.get("error")
    if isinstance(error, dict):
        error = f"{error.get('type')}: {error.get('message')}"
    return {**{column: event.get(column) for column in CSV_COLUMNS}, "error": error}


def _line(event: dict) -> str:
    """Return one event as one line: time, event, case, status, error."""
    parts = [str(event.get("at") or ""), str(event.get("event") or "")]
    if event.get("case_id"):
        parts.append(str(event["case_id"]))
    if event.get("status"):
        parts.append(str(event["status"]))
    error = event.get("error")
    if isinstance(error, dict):
        parts.append(f"{error.get('type')}: {error.get('message')}")
    elif error:
        parts.append(str(error))
    elif event.get("status") not in (None, "completed") and event.get("log_tail"):
        parts.append(str(event["log_tail"][-1]))
    if event.get("rel_dir"):
        parts.append(str(event["rel_dir"]))
    return "  ".join(part for part in parts if part)
