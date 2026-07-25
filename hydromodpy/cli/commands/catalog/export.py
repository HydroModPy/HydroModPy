"""``hmp catalog export`` - write a run as a portable ``.hmp`` archive."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, exit_code_for
from hydromodpy.core.state.paths import resolve_project_root

NAME: str = "export"
HELP: str = "Export a run as a portable .hmp archive (config, provenance, fields, timeseries)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser()],
        epilog=(
            "Examples:\n"
            "  hmp catalog export cheze_baseline.v3 -o paper.hmp\n"
            "  hmp catalog export trial-007 trial-013 -o paper2026/"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "sim_refs",
        nargs="+",
        metavar="SIM_REF",
        help="One or more run references. Multiple refs write one multi-run .hmp container.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help=(
            "Destination .hmp path. Single ref defaults to <name>.hmp; multiple "
            "refs default to runs.hmp (one container holding every run)."
        ),
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import export_package_run, export_package_runs

    workspace_root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        if len(args.sim_refs) == 1:
            single = export_package_run(
                args.sim_refs[0], workspace=workspace_root, output=args.output
            )
            print(f"wrote {single['path']}  [{single['sim_id'][:8]}]")
        else:
            multi = export_package_runs(args.sim_refs, workspace=workspace_root, output=args.output)
            ids = ", ".join(s[:8] for s in multi["sim_ids"])
            print(f"wrote {multi['path']}  ({len(multi['sim_ids'])} runs: {ids})")
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except Exception as exc:  # noqa: BLE001 - map resolver errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
