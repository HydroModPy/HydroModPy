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
    EXIT_CALIBRATION,
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_SIGINT,
    profile_arg_from_toml,
    profile_run,
    resolve_profile_output,
)
from hydromodpy.core.exceptions import CalibrationError

NAME: str = "calibrate"
HELP: str = "Run a calibration workflow from a TOML config"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP, parents=[profile_parser()])
    parser.add_argument("config", type=Path, help="Path to a calibration TOML file")
    parser.add_argument(
        "--phase",
        default=None,
        help="Run only this phase of a staged calibration. Its dependency must have "
        "run, otherwise the phase would calibrate against un-frozen parameters.",
    )
    parser.add_argument(
        "--list-phases",
        action="store_true",
        help="List the declared phases and exit without running anything.",
    )
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

    profile_arg = getattr(args, "profile", None)
    if profile_arg is None:
        from hydromodpy.core.toml_io.loader import load_toml_with_base_config

        try:
            profile_arg = profile_arg_from_toml(load_toml_with_base_config(target))
        except Exception:
            profile_arg = None
    if args.list_phases:
        try:
            phases = hmp.calibrate(target, list_phases=True)
        except ValidationError as exc:
            print(f"Config invalid: {exc}", file=sys.stderr)
            sys.exit(EXIT_CONFIG)
        if not phases:
            print(f"{target.name} declares no phases.", file=sys.stderr)
            return
        for index, phase in enumerate(phases):
            print(f"{index}\t{phase['name']}\t{phase['method']}\t{phase['description']}")
        return

    profile_output = resolve_profile_output(profile_arg, target)
    try:
        with profile_run(profile_output, description=f"hmp calibrate {target.name}"):
            result = hmp.calibrate(target, phase=args.phase)
    except KeyboardInterrupt:
        print("Aborted by user.", file=sys.stderr)
        sys.exit(EXIT_SIGINT)
    except ValidationError as exc:
        print(f"Config invalid: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except FileNotFoundError as exc:
        print(f"Missing file: {exc}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except CalibrationError as exc:
        print(f"Calibration failed: {exc}", file=sys.stderr)
        sys.exit(EXIT_CALIBRATION)

    print(f"Calibration finished: {target.name}", file=sys.stderr)
    if result is None:
        return
    summary = getattr(result, "summary", None)
    if isinstance(summary, dict):
        for key, value in summary.items():
            print(f"  {key}: {value}", file=sys.stderr)
