"""``hmp diff`` - compare runs.

Two runs, with nothing else asked, print what differs in their parameters and
their metrics, read from the index. ``--to DIR`` (or ``--by site``, ``--variables``,
or more than two runs) writes the comparison of sealed runs of one site as a folder
with its README: differences, parameters, scores, budget, network, maps and series.
``hydromodpy.project.api.compare`` does that second reading.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

from hydromodpy.cli.conventions import (
    add_destination,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_VALIDATION, project_root_of, refuse
from hydromodpy.cli.output import emit
from hydromodpy.core.scope import CATCHMENT
from hydromodpy.core.state.layout import summary_dir_for
from hydromodpy.results.storage.contract import RUN_REPORT_DIRNAME

NAME: str = "diff"
HELP: str = "Compare runs: their parameters and metrics, or a folder with the whole comparison"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog=(
            "Examples:\n"
            "  hmp diff my_run.v2 my_run.v3\n"
            "  hmp diff k_low k_high --to ../k_study\n"
            "  hmp diff calage_nm calage_tpe --by site\n"
            "  hmp diff runs/coarse runs/fine --to ../mesh_study"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "refs",
        nargs="+",
        metavar="REF",
        help=(
            "A run directory, a run name under runs/ (base.v2), or a recipe (the latest run "
            "of each of its cases). The first run is the reference."
        ),
    )
    parser.add_argument(
        "--by",
        choices=("site",),
        default=None,
        help=(
            "Compare the runs of each site separately, one folder per site, and join "
            "their scores in by_site.csv."
        ),
    )
    parser.add_argument(
        "--variables",
        default=None,
        help=(
            "Comma-separated variables mapped at the last shared date. Default: the head "
            "and the depth to the water table when every run has them."
        ),
    )
    add_destination(
        parser,
        help="Folder of the comparison. Default: summary/report/compare/<refs>/ of the project.",
        metavar="DIR",
    )
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
    folder_asked = bool(args.to or args.by or args.variables or len(args.refs) != 2)
    if folder_asked:
        _folder(args)
    else:
        _delta(args)


def _delta(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog.listing import diff_simulations

    workspace_root = project_root_of(args)
    result = diff_simulations(args.refs[0], args.refs[1], workspace=workspace_root)

    def table() -> None:
        print(f"a: {result['a'][:8]}   b: {result['b'][:8]}")
        _print_delta("params", result["params"])
        _print_metrics(result["metrics"])

    emit(
        args,
        "diff",
        {
            "a": result["a"],
            "b": result["b"],
            "params": _delta_to_list(result["params"]),
            "metrics": _metrics_to_list(result["metrics"]),
        },
        table=table,
    )


def compare_folder(refs: list[str], project_root: Path | None) -> Path:
    """Return ``summary/report/compare/<refs>/`` of the project."""
    from hydromodpy.project.compare import ComparisonCaseError

    if project_root is None:
        raise ComparisonCaseError("No project around the runs to write into: pass --to DIR.")
    slugs = [re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(ref).name or ref).strip("_") for ref in refs]
    name = "-vs-".join(slug for slug in slugs if slug)
    if not name or len(name) > 96:
        name = hashlib.sha256("\n".join(refs).encode("utf-8")).hexdigest()[:12]
    return summary_dir_for(project_root) / RUN_REPORT_DIRNAME / "compare" / name


def _folder(args: argparse.Namespace) -> None:
    from hydromodpy.core.console import progress
    from hydromodpy.project.api import compare
    from hydromodpy.project.compare import ComparisonCaseError, ComparisonReferenceError

    root = project_root_of(args)
    variables = (
        [item.strip() for item in args.variables.split(",") if item.strip()]
        if args.variables
        else None
    )
    try:
        with progress.status("Comparing runs"):
            folder = Path(args.to) if args.to else compare_folder(args.refs, root)
            result = compare(
                args.refs, variables=variables, out=folder, by=args.by or "run", workspace=root
            )
    except ComparisonReferenceError as exc:
        refuse(str(exc), EXIT_NOT_FOUND, cause=exc)
    except ComparisonCaseError as exc:
        refuse(str(exc), EXIT_VALIDATION, cause=exc)
    written = result if isinstance(result, Path) else folder
    emit(
        args,
        "diff folder",
        {"folder": written},
        table=lambda: print(f"wrote {written}", file=sys.stderr),
    )
