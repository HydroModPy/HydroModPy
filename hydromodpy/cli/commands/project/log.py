"""``hmp project log``: the journal of the latest launch, or its failed cases."""

from __future__ import annotations

import argparse
import csv
import json
import sys

from hydromodpy.cli._conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import apply_verbosity, exit_code_for

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
    apply_verbosity(args, {})
    from hydromodpy.cli._workers.project import sites_project_root
    from hydromodpy.project.launch import read_journal

    try:
        events = read_journal(
            sites_project_root(args.project or args.workspace or "."),
            failed_only=bool(args.failed),
            job=args.job,
        )
    except Exception as exc:  # noqa: BLE001 - map errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    if args.format == "json":
        print(json.dumps(events, indent=2, default=str))
        return
    if args.format == "csv":
        _write_csv(events)
        return
    if not events:
        print("no failed case" if args.failed else "no launch journal")
        return
    for event in events:
        print(_line(event))


CSV_COLUMNS: tuple[str, ...] = (
    "at",
    "event",
    "case_id",
    "status",
    "exit_code",
    "signal",
    "rel_dir",
    "error",
    "log",
)
"""Columns of ``--format csv``: one row per event; fields an event lacks stay empty."""


def _write_csv(events: list[dict]) -> None:
    """Write the events as CSV, the error as one ``type: message`` cell."""
    writer = csv.DictWriter(sys.stdout, fieldnames=list(CSV_COLUMNS), extrasaction="ignore")
    writer.writeheader()
    for event in events:
        error = event.get("error")
        if isinstance(error, dict):
            error = f"{error.get('type')}: {error.get('message')}"
        row = {column: event.get(column) for column in CSV_COLUMNS}
        row["error"] = error
        writer.writerow({key: "" if value is None else value for key, value in row.items()})


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
