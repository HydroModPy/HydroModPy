"""``hmp site-selection`` - validate and plan site-selection configs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_OK

NAME: str = "site-selection"
HELP: str = "Plan and inspect site-selection workflows"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="site_selection_command", required=True)

    plan = sub.add_parser("plan", help="Validate a site-selection TOML and print its plan")
    plan.add_argument("config", type=Path, help="Path to a TOML config with [site_selection]")
    plan.add_argument(
        "--write-manifest",
        action="store_true",
        help="Write site_selection_plan.json under output_root",
    )
    plan.add_argument(
        "--write-report",
        action="store_true",
        help="Write review/index.html from the plan manifest",
    )
    plan.set_defaults(_handler=run_plan)

    select = sub.add_parser(
        "select-catchments",
        help="Apply a site-selection config to a pre-delineated catchments CSV",
    )
    select.add_argument("config", type=Path, help="Path to a TOML config with [site_selection]")
    select.add_argument(
        "catchments_csv",
        type=Path,
        help="CSV with site_id, x/y or x_outlet/y_outlet, and optional area_km2/status.",
    )
    select.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Override [site_selection].output_root for this selection pass.",
    )
    select.add_argument(
        "--region-id",
        default="",
        help="Optional region_id written to selected/regional-lab site CSVs.",
    )
    select.set_defaults(_handler=run_select_catchments)

    build_observed = sub.add_parser(
        "build-observed",
        help="Build observation-led site selection from [site_selection] and [hydrometry]",
    )
    build_observed.add_argument(
        "config",
        type=Path,
        help="Path to a TOML config with [site_selection] and [hydrometry].",
    )
    build_observed.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Override [site_selection].output_root for this build.",
    )
    build_observed.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help="Optional HydroModPy workspace root used for data caching.",
    )
    build_observed.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Optional data root used for data caching.",
    )
    build_observed.set_defaults(_handler=run_build_observed)

    report = sub.add_parser(
        "report",
        help="Render the static HTML report from a site_selection_manifest.json",
    )
    report.add_argument(
        "manifest",
        type=Path,
        help="Path to a site_selection_manifest.json file.",
    )
    report.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output HTML path. Defaults to <output_root>/review/index.html.",
    )
    report.set_defaults(_handler=run_report)
    return parser


def run_plan(args: argparse.Namespace) -> None:
    from hydromodpy.workflow.site_selection import plan_site_selection

    config_path = Path(args.config).expanduser()
    if not config_path.is_file():
        print(f"File not found: {config_path}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    try:
        plan = plan_site_selection(config_path)
    except (ValueError, ValidationError) as exc:
        print(f"Invalid site-selection config: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    manifest_path = None
    if args.write_manifest or args.write_report:
        manifest_path = plan.write_manifest()
        print(f"[written] {manifest_path}")

    if args.write_report:
        from hydromodpy.spatial.site_selection.plan_report import (
            render_site_selection_plan_html_report,
        )

        assert manifest_path is not None
        report_path = render_site_selection_plan_html_report(manifest_path)
        print(f"[written] site_selection_report_html: {report_path}")

    print(json.dumps(plan.manifest, indent=2, sort_keys=True))
    sys.exit(EXIT_OK)


def run_select_catchments(args: argparse.Namespace) -> None:
    from hydromodpy.workflow.site_selection import select_delineated_catchments_from_csv

    config_path = Path(args.config).expanduser()
    catchments_path = Path(args.catchments_csv).expanduser()
    if not config_path.is_file():
        print(f"File not found: {config_path}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    if not catchments_path.is_file():
        print(f"File not found: {catchments_path}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    try:
        result, paths = select_delineated_catchments_from_csv(
            config_path=config_path,
            catchments_csv=catchments_path,
            output_root=args.output_root,
            region_id=args.region_id,
        )
    except (ValueError, ValidationError) as exc:
        print(f"Invalid site-selection input: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    for label, path in paths.items():
        print(f"[written] {label}: {path}")
    print(f"selected={len(result.selected)} rejected={len(result.rejected)}")
    sys.exit(EXIT_OK)


def run_build_observed(args: argparse.Namespace) -> None:
    from hydromodpy.workflow.site_selection import build_observed_site_selection_from_toml

    config_path = Path(args.config).expanduser()
    if not config_path.is_file():
        print(f"File not found: {config_path}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    try:
        result = build_observed_site_selection_from_toml(
            config_path=config_path,
            output_root=args.output_root,
            workspace_root=args.workspace_root,
            data_root=args.data_root,
        )
    except (ValueError, ValidationError) as exc:
        print(f"Invalid site-selection input: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    for label, path in result.output_paths.items():
        print(f"[written] {label}: {path}")
    print(f"candidates={len(result.candidates)}")
    print(f"selected={len(result.selection.selected)} rejected={len(result.selection.rejected)}")
    sys.exit(EXIT_OK)


def run_report(args: argparse.Namespace) -> None:
    from hydromodpy.spatial.site_selection.html_report import (
        render_site_selection_html_report,
    )

    manifest_path = Path(args.manifest).expanduser()
    if not manifest_path.is_file():
        print(f"File not found: {manifest_path}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    try:
        html_path = render_site_selection_html_report(
            manifest_path,
            output_path=args.output,
        )
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        print(f"Invalid site-selection manifest: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    print(f"[written] site_selection_report_html: {html_path}")
    sys.exit(EXIT_OK)


__all__ = [
    "register",
    "run_build_observed",
    "run_plan",
    "run_report",
    "run_select_catchments",
]
