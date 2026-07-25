"""``hmp catalog rerun`` - re-launch a run from its snapshot with overrides."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import add_sim_ref, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_USAGE, exit_code_for
from hydromodpy.core.state.paths import resolve_project_root

NAME: str = "rerun"
HELP: str = "Re-launch a run from its config snapshot with --set path=value overrides"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser()],
        epilog="Example:\n  hmp catalog rerun cheze_baseline --set flow.hydraulic_conductivity=2e-4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser)
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="PATH=VALUE",
        dest="overrides",
        help="Dotted config path override, repeatable (e.g. flow.hydraulic_conductivity=2e-4)",
    )
    parser.add_argument("--name", default=None, help="Name for the new run")
    parser.set_defaults(_handler=run)
    return parser


def _coerce(value: str):
    for caster in (int, float):
        try:
            return caster(value)
        except ValueError:
            continue
    low = value.lower()
    if low in ("true", "false"):
        return low == "true"
    return value


def _parse_overrides(items: list[str]) -> dict:
    overrides: dict = {}
    for item in items:
        if "=" not in item:
            print(f"Invalid --set {item!r}; expected PATH=VALUE.", file=sys.stderr)
            sys.exit(EXIT_USAGE)
        path, _, raw = item.partition("=")
        overrides[path.strip()] = _coerce(raw.strip())
    return overrides


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import rerun_simulation

    overrides = _parse_overrides(args.overrides)
    workspace_root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        result = rerun_simulation(
            args.sim_ref, workspace=workspace_root, overrides=overrides, name=args.name
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except Exception as exc:  # noqa: BLE001 - map resolver / launch errors to exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    print(f"reran as {result['name'] or result['sim_id'][:8]}  [{result['sim_id'][:8]}]")
