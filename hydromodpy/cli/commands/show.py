"""``hmp show`` - read one calibration session, or one run, at a glance.

``hmp show REF`` prints the summary of a calibration session: its trials by
status, the bounds the best trial reached, why the search stopped, the report
page and where the time went. A reference that names a run goes to
``hmp catalog show``, which prints the run.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from hydromodpy.cli.conventions import (
    add_sim_ref,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, project_root_of, refuse
from hydromodpy.cli.output import emit

NAME: str = "show"
HELP: str = "Print a calibration session at a glance, or a run"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog="Examples:\n  hmp show calage\n  hmp show calage.v2 --format json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(
        parser,
        help="A session (<case>[.vN] or sessions/<case>[.vN]), or a run, as hmp catalog show reads it.",
    )
    parser.set_defaults(_handler=run, detail=False)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.core.exceptions import ConfigMissingError
    from hydromodpy.results.session.descriptor import resolve_session_dir

    project_root = project_root_of(args)
    try:
        directory = resolve_session_dir(project_root, args.sim_ref)
    except ConfigMissingError:
        # Not a session of this project: the reference is a run.
        from hydromodpy.cli.commands.catalog import show as catalog_show

        catalog_show.run(args)
        return
    payload, rows = _session_payload(directory)
    emit(args, "show", payload, table=lambda: _print_session(directory, payload, rows))


def _session_payload(directory: Path) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    from hydromodpy.core.exceptions import HydroModPyError
    from hydromodpy.results.session.summary import session_summary, summary_rows
    from hydromodpy.results.session.view import Session

    try:
        summary = session_summary(Session(directory))
    except (HydroModPyError, OSError, ValueError) as exc:
        refuse(f"session {directory.name} cannot be read: {exc}", EXIT_NOT_FOUND, cause=exc)
    payload = asdict(summary)
    payload["report"] = None if summary.report is None else str(summary.report)
    return payload, summary_rows(summary)


def _print_session(directory: Path, payload: dict[str, Any], rows: list[tuple[str, str]]) -> None:
    width = max(len(label) for label, _ in rows)
    for label, text in rows:
        print(f"{label.ljust(width)} : {text}")
    if payload["report"] is None:
        print(f"report: not written; hmp report render {directory.name} writes it")
    else:
        print(f"report: {payload['report']}")
    print(f"next: hmp report render {directory.name}", file=sys.stderr)
