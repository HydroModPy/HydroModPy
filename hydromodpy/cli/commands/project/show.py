"""``hmp project show`` - what a project holds, read from its directories.

Disk is the truth: the counts come from ``runs/``, ``sessions/``, ``plan/``,
``summary/`` and ``trash/``, never from the index, which is only reported as
present or missing.

The positional reads like the other ``hmp project`` verbs: a path (``.``,
``..``, anything with a slash) is the project at or above it, a bare name is
``projects/<name>`` of the workspace. Nothing found stops with a named
refusal, never a listing of the wrong folder.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import apply_verbosity, resolve_project_ref
from hydromodpy.core.state.paths import (
    CATALOG_FILENAME,
    INTERNAL_DIRNAME,
    PROJECT_MARKER_FILENAME,
    catalog_path_for,
    summary_dir_for,
)

NAME: str = "show"
HELP: str = "Show what a project holds: configs, runs by status, sessions, plan, trash"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog=(
            "Examples:\n"
            "  hmp project show my_project -w ~/hydromodpy\n"
            "  hmp project show .\n"
            "  hmp project show -w ~/hydromodpy/projects/my_project --format json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=None,
        help=(
            "A project name under projects/, or a path ('.', '..', a/b) to a project "
            "(default: the project of -w or of the cwd)"
        ),
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    project_dir = resolve_project_ref(args.workspace, args.project)
    payload = _summary(project_dir)

    if args.format == "json":
        print(json.dumps(payload, indent=2, default=str))
        return
    if args.format == "csv":
        print("key,value")
        for key, value in payload.items():
            print(f"{key},{_flat(value)}")
        return

    print(f"# project: {payload['name']}")
    print(f"# path   : {payload['path']}")
    state = "present" if payload["has_project_toml"] else "missing"
    print(f"  {PROJECT_MARKER_FILENAME:<24} {state}")
    configs = payload["configs"]
    if configs:
        print(f"  configs ({len(configs)}): {', '.join(configs)}")
    print(f"  runs     : {payload['n_runs']}{_by_status(payload['runs'])}")
    print(f"  sessions : {payload['n_sessions']}{_by_status(payload['sessions'])}")
    if payload["n_trials"]:
        print(f"  kept trials: {payload['n_trials']}")
    print(f"  plan     : {payload['plan'] or 'none'}")
    print(f"  summary  : {'summary/' if payload['has_summary'] else 'none'}")
    print(f"  trash    : {payload['n_trashed']} entr{'y' if payload['n_trashed'] == 1 else 'ies'}")
    index_label = f"{INTERNAL_DIRNAME}/{CATALOG_FILENAME}"
    index_state = "present" if payload["has_index"] else "missing (hmp catalog reindex builds it)"
    print(f"  index    : {index_label} {index_state}")


def _summary(project_dir: Path) -> dict:
    from hydromodpy.results.catalog.indexer import scan_tree
    from hydromodpy.results.outcome import effective_status
    from hydromodpy.results.plan_store import current_plan_hash
    from hydromodpy.results.session.descriptor import list_session_dirs, read_session
    from hydromodpy.results.storage.json_io import readable
    from hydromodpy.results.trash import list_trash

    entries = scan_tree(project_dir)
    runs = Counter(effective_status(e.path) for e in entries.values() if e.kind == "run")
    n_trials = sum(1 for e in entries.values() if e.kind == "trial")
    descriptors = (readable(read_session, path) for path in list_session_dirs(project_dir))
    sessions = Counter("unreadable" if each is None else each.status for each in descriptors)
    return {
        "name": project_dir.name,
        "path": str(project_dir),
        "has_project_toml": (project_dir / PROJECT_MARKER_FILENAME).is_file(),
        "configs": sorted(
            path.name for path in project_dir.glob("*.toml") if path.name != PROJECT_MARKER_FILENAME
        ),
        "n_runs": sum(runs.values()),
        "runs": dict(sorted(runs.items())),
        "n_sessions": sum(sessions.values()),
        "sessions": dict(sorted(sessions.items())),
        "n_trials": n_trials,
        "plan": current_plan_hash(project_dir),
        "has_summary": summary_dir_for(project_dir).is_dir(),
        "n_trashed": len(list_trash(project_dir)),
        "has_index": catalog_path_for(project_dir).is_file(),
    }


def _by_status(counts: dict[str, int]) -> str:
    if not counts:
        return ""
    return " (" + ", ".join(f"{status} {n}" for status, n in counts.items()) + ")"


def _flat(value: object) -> str:
    if isinstance(value, dict):
        return ";".join(f"{key}={item}" for key, item in value.items())
    if isinstance(value, list):
        return ";".join(str(item) for item in value)
    return "" if value is None else str(value)
