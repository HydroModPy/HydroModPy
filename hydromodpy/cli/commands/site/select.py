"""``hmp site select``: run the site selection a TOML file declares."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from hydromodpy.cli._conventions import workspace_parser
from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_USAGE, exit_code_for
from hydromodpy.core import progress
from hydromodpy.core.logging import get_logger

NAME: str = "select"
HELP: str = "Run the site selection a TOML file declares"

logger = get_logger(__name__)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser()],
        epilog=(
            "The review report (review/index.html) is rendered by the run itself when\n"
            "[site_selection.output] write_report_html = true; no other verb renders it.\n"
            "\n"
            "Examples:\n"
            "  hmp site select selection.toml --dry-run\n"
            "  hmp site select selection.toml --into-catalog"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("config", type=Path, help="TOML file with a [site_selection] section")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the file and print the plan; write nothing",
    )
    parser.add_argument(
        "--into-catalog",
        action="store_true",
        help="Declare the selected sites in data/sites/catalog.csv of the workspace",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="With --into-catalog: replace sites of the same name, accept close outlets",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.reporting.site_selection.html import render_site_selection_html_report
    from hydromodpy.reporting.site_selection.plan import render_site_selection_plan_html_report
    from hydromodpy.workflow.site_selection.selection_plan import plan_site_selection
    from hydromodpy.workflow.site_selection.selection_run import run_site_selection

    config_path = Path(args.config).expanduser()
    if not config_path.is_file():
        print(f"File not found: {config_path}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    if args.dry_run and args.into_catalog:
        print("--into-catalog declares the sites a run selects; drop --dry-run.", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    root = None
    if args.into_catalog:
        from hydromodpy.cli.helpers import resolve_workspace

        root = resolve_workspace(args.workspace)

    try:
        if args.dry_run:
            plan = plan_site_selection(config_path)
            print(json.dumps(plan.manifest, indent=2, sort_keys=True))
            return
        with progress.status("Site selection") as handle:
            selection = run_site_selection(
                config_path,
                report_renderer=render_site_selection_html_report,
                plan_report_renderer=render_site_selection_plan_html_report,
                progress_callback=_progress_callback(handle),
            )
    except (ValueError, ValidationError) as exc:
        print(f"Invalid site selection: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except Exception as exc:  # noqa: BLE001 - map errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    for label, path in selection.outputs.items():
        print(f"[written] {label}: {path}")
    print(" ".join(f"{key}={value}" for key, value in selection.counts.items()))
    if root is not None:
        _into_catalog(root, selection, force=args.force)


def _into_catalog(root: Path, selection, *, force: bool) -> None:
    from hydromodpy.data.sites.catalog import catalog_path, declare_sites
    from hydromodpy.data.sites.importers import rows_from_selection

    manifest = selection.outputs.get("site_selection_manifest_json")
    if manifest is None:
        print(
            f"The {selection.action} action writes no manifest: no site to declare.",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)
    try:
        rows = rows_from_selection(Path(manifest)).rows
        declare_sites(root, rows, force=force)
    except Exception as exc:  # noqa: BLE001 - map errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    print(f"[written] {len(rows)} site(s): {catalog_path(root)}")


def _progress_callback(handle: progress.TaskHandle) -> Callable[[str], None]:
    def _callback(message: str) -> None:
        handle.update(description=message)
        logger.debug("%s", message)

    return _callback
