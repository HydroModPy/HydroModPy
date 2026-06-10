"""``hmp calibrate`` - run a calibration workflow from a TOML file.

Thin wrapper around :func:`hydromodpy.calibrate`. The TOML must declare
``[workflow] mode = "calibration"`` (resolved by the workflow dispatcher).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from hydromodpy.cli._conventions import profile_parser
from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_SIGINT,
    profile_run,
    resolve_profile_output,
)

NAME: str = "calibrate"
HELP: str = "Run a calibration workflow from a TOML config"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP, parents=[profile_parser()])
    parser.add_argument("config", type=Path, help="Path to a calibration TOML file")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    import hydromodpy as hmp

    target = Path(args.config).expanduser().resolve()
    if not target.is_file():
        print(f"File not found: {target}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    if target.suffix != ".toml":
        print(f"Expected a .toml file, got: {target.suffix}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    profile_output = resolve_profile_output(getattr(args, "profile", None), target)
    try:
        with profile_run(profile_output):
            result = hmp.calibrate(target)
    except KeyboardInterrupt:
        print("Aborted by user.", file=sys.stderr)
        sys.exit(EXIT_SIGINT)
    except ValidationError as exc:
        print(f"Config invalid: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except FileNotFoundError as exc:
        print(f"Missing file: {exc}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    print(f"Calibration finished: {target.name}", file=sys.stderr)
    if result is None:
        return
    summary = getattr(result, "summary", None)
    if isinstance(summary, dict):
        for key, value in summary.items():
            print(f"  {key}: {value}", file=sys.stderr)
