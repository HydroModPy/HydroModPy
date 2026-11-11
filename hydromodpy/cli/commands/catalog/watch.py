"""``hmp catalog watch`` - the running attempts of a project and the age of their pulse."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, project_root_of, refuse
from hydromodpy.cli.output import emit

NAME: str = "watch"
HELP: str = "Show the running attempts with the age of their heartbeat"


def register(subparsers) -> argparse.ArgumentParser:
    from hydromodpy.results.outcome import DEFAULT_STALE_AFTER_S

    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        description=(
            "Read the outcome.json and logs/heartbeat.json of every run directory and list "
            "the attempts that are running. The index is never opened: this answers while "
            "a solve is going on and on a project that has no index yet."
        ),
        epilog="Example:\n  hmp catalog watch --stale-minutes 5",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--stale-minutes",
        type=float,
        default=DEFAULT_STALE_AFTER_S / 60.0,
        help="Heartbeat age (minutes) beyond which a running attempt is flagged stale",
    )
    parser.set_defaults(_handler=run)
    return parser


def _age(age_s: float | None) -> str:
    if age_s is None:
        return "no heartbeat"
    if age_s < 60:
        return f"{int(age_s)}s ago"
    if age_s < 3600:
        return f"{int(age_s // 60)}m ago"
    return f"{age_s / 3600:.1f}h ago"


def run(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog.liveness import watch_running

    project_root = project_root_of(args)
    if not project_root.is_dir():
        refuse(f"No project at {project_root}", EXIT_NOT_FOUND)
    from hydromodpy.core.state.host import death_is_proven

    # A worker of this host whose pid is gone died without a word (OOM, SIGKILL).
    rows = [
        {**entry, "dead": death_is_proven(entry["host"], entry["pid"])}
        for entry in watch_running(project_root, stale_minutes=args.stale_minutes)
    ]

    def table() -> None:
        if not rows:
            print("no running attempt.")
            return
        print(f"# running ({len(rows)})")
        for entry in rows:
            flag = "dead" if entry["dead"] else ("STALE" if entry["stale"] else "live")
            step = f"  step={entry['step']}" if entry["step"] else ""
            print(
                f"  [{flag}]  {entry['rel_dir']}  attempt {entry['attempt']}  "
                f"{entry['host']}:{entry['pid']}{step}  heartbeat {_age(entry['age_s'])}"
            )

    emit(args, "catalog watch", rows, table=table)
