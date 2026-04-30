"""``hmp report <session_id>`` - generate an HTML report for a calibration session.

Reads the ``calibration_sessions`` + ``calibration_iterations`` tables in
the workspace DuckDB, renders the six calibration figures into a single
HTML page, and drops the result under
``<workspace>/reports/<session_id>/report.html``.

Usage
-----
``hmp report <session_id>``           Full session id (UUID hex or dashed).
``hmp report <short_prefix>``         First ≥8 hex chars (must be unique).
``hmp report <session_id> --open``    Open the HTML in the default browser.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, find_workspace_root

NAME: str = "report"
HELP: str = "Render an HTML report for a calibration session"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "session_id",
        help="Calibration session UUID (full or unambiguous short prefix)",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        metavar="PATH",
        help="Workspace root (defaults to ancestor of CWD).",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        dest="open_browser",
        help="Open the generated HTML in the default browser on completion.",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.calibration.report import resolve_calibration_session_id
    from hydromodpy.core.exceptions import ConfigError, ConfigMissingError
    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.workflow.steps.calibration import step_render_calibration_report

    workspace_root = args.workspace or find_workspace_root(Path.cwd())
    with SimulationCatalog(workspace_root) as catalog:
        try:
            session_id = resolve_calibration_session_id(catalog, args.session_id)
        except ConfigMissingError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        except ConfigError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(EXIT_CONFIG)
        out_path = step_render_calibration_report(
            catalog=catalog,
            session_id=session_id,
            workspace_root=workspace_root,
        )
    print(f"wrote {out_path}", file=sys.stderr)
    if args.open_browser:
        import webbrowser

        webbrowser.open(out_path.as_uri())
