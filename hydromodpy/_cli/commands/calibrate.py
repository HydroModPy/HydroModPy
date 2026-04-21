"""``hmp calibrate`` — run a parameter calibration campaign."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy._cli.helpers import EXIT_NOT_FOUND


NAME = "calibrate"
HELP = "Run a calibration campaign from a TOML config"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "config", type=Path,
        help="Path to a TOML with a [calibration] section",
    )
    parser.add_argument(
        "--objective", default=None,
        help="Python entry-point 'module.path:callable' (evaluator function)",
    )
    parser.add_argument(
        "--workspace", default=None,
        help="Workspace directory (default: TOML parent directory)",
    )
    parser.add_argument(
        "--project", default="calibration",
        help="Project label to tag the session (default: calibration)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.calibration.cli import run_calibration_cli

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        print(f"File not found: {config_path}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    summary = run_calibration_cli(
        config_path,
        objective=getattr(args, "objective", None),
        workspace=getattr(args, "workspace", None),
        project=getattr(args, "project", "calibration"),
    )
    print("Calibration complete:", file=sys.stderr)
    for key, value in summary.items():
        print(f"  {key}: {value}", file=sys.stderr)
