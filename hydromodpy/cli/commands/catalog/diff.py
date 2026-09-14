"""``hmp catalog diff`` - compare two runs' parameters and outlet metrics."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import format_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, exit_code_for
from hydromodpy.core.state.paths import resolve_project_root

NAME: str = "diff"
HELP: str = "Compare two runs' parameters and outlet metrics"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser()],
        epilog="Example:\n  hmp catalog diff cheze_baseline.v2 cheze_baseline.v3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("ref_a", help="First run reference")
    parser.add_argument("ref_b", help="Second run reference")
    parser.set_defaults(_handler=run)
    return parser


def _delta_to_list(delta: dict) -> list[dict]:
    """Flatten a ``{(name, scope): (a, b)}`` delta into JSON-serialisable rows."""
    return [
        {"name": name, "scope": scope, "a": a, "b": b} for (name, scope), (a, b) in delta.items()
    ]


def _print_delta(title: str, delta: dict) -> None:
    if not delta:
        print(f"{title}: identical")
        return
    print(f"{title}:")
    for (name, scope), (a, b) in delta.items():
        scope_str = "" if scope in (None, "__outlet__", "__global__") else f"@{scope}"
        print(f"  {name}{scope_str}: {a!r} -> {b!r}")


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import diff_simulations

    workspace_root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        result = diff_simulations(args.ref_a, args.ref_b, workspace=workspace_root)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except Exception as exc:  # noqa: BLE001 - map resolver errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    if args.format == "json":
        import json

        print(
            json.dumps(
                {
                    "a": result["a"],
                    "b": result["b"],
                    "params": _delta_to_list(result["params"]),
                    "metrics": _delta_to_list(result["metrics"]),
                },
                default=str,
            )
        )
        return

    print(f"a: {result['a'][:8]}   b: {result['b'][:8]}")
    _print_delta("params", result["params"])
    _print_delta("metrics", result["metrics"])
