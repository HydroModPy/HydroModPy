"""``hmp catalog watch`` - snapshot of running runs and heartbeat health."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, find_catalog_root

NAME: str = "watch"
HELP: str = "Show running simulations with heartbeat age and staleness"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser()],
        epilog="Example:\n  hmp catalog watch --stale-minutes 5",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--stale-minutes",
        type=int,
        default=10,
        help="Heartbeat age (minutes) beyond which a run is flagged stale",
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
    from hydromodpy.cli._workers.catalog import watch_running

    workspace_root = find_catalog_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        rows = watch_running(workspace_root, stale_minutes=args.stale_minutes)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    if not rows:
        print("no running simulations.")
        return
    print(f"# running ({len(rows)})")
    for entry in rows:
        flag = "STALE" if entry["stale"] else "live"
        name = entry["name"] or "(no name)"
        print(f"  [{flag}]  {name}  [{entry['sim_id'][:8]}]  heartbeat {_age(entry['age_s'])}")
