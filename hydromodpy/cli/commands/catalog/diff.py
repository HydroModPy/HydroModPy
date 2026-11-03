"""``hmp catalog diff`` - compare two runs' parameters and metrics."""

from __future__ import annotations

import argparse
from pathlib import Path

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import apply_verbosity
from hydromodpy.cli.output import emit
from hydromodpy.core.scope import CATCHMENT
from hydromodpy.core.state.paths import resolve_project_root

NAME: str = "diff"
HELP: str = "Compare two runs' parameters and metrics"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog="Example:\n  hmp catalog diff my_run.v2 my_run.v3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("ref_a", help="First run reference")
    parser.add_argument("ref_b", help="Second run reference")
    parser.set_defaults(_handler=run)
    return parser


def _delta_to_list(delta: dict) -> list[dict]:
    """Flatten a ``{(name, scope): (a, b)}`` delta into JSON-serializable rows."""
    return [
        {"name": name, "scope": scope, "a": a, "b": b} for (name, scope), (a, b) in delta.items()
    ]


def _side_of(entry: dict | None) -> dict | None:
    if entry is None:
        return None
    return {
        "value": entry["value"],
        "window": _window_text(entry),
        "n": entry["n"],
    }


def _window_text(entry: dict) -> str | None:
    if entry["window_start"] is None:
        return None
    return f"{entry['window_start']}/{entry['window_end']}"


def _metrics_to_list(delta: dict) -> list[dict]:
    """Flatten a ``{(metric, station, variable): (a, b)}`` delta into JSON-serializable rows."""
    return [
        {
            "name": name,
            "station": station,
            "variable": variable,
            "a": _side_of(a),
            "b": _side_of(b),
        }
        for (name, station, variable), (a, b) in delta.items()
    ]


def _print_metrics(delta: dict) -> None:
    if not delta:
        print("metrics: identical")
        return
    print("metrics:")
    for (name, station, variable), (a, b) in delta.items():
        where = "/".join(str(part) for part in (station, variable) if part)
        label = f"{name}@{where}" if where else name
        print(f"  {label}: {_side_text(a)} -> {_side_text(b)}")


def _side_text(entry: dict | None) -> str:
    if entry is None:
        return "absent"
    window = _window_text(entry)
    scored_on = "no window" if window is None else window
    return f"{entry['value']!r} [{scored_on}, n={entry['n']}]"


def _print_delta(title: str, delta: dict) -> None:
    if not delta:
        print(f"{title}: identical")
        return
    print(f"{title}:")
    for (name, scope), (a, b) in delta.items():
        scope_str = "" if scope in (None, "", CATCHMENT) else f"@{scope}"
        print(f"  {name}{scope_str}: {a!r} -> {b!r}")


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.cli._workers.catalog import diff_simulations

    workspace_root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    result = diff_simulations(args.ref_a, args.ref_b, workspace=workspace_root)

    def table() -> None:
        print(f"a: {result['a'][:8]}   b: {result['b'][:8]}")
        _print_delta("params", result["params"])
        _print_metrics(result["metrics"])

    emit(
        args,
        "catalog diff",
        {
            "a": result["a"],
            "b": result["b"],
            "params": _delta_to_list(result["params"]),
            "metrics": _metrics_to_list(result["metrics"]),
        },
        table=table,
    )
