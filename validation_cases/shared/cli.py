"""Shared CLI helpers for analytical validation-case runner scripts."""

from __future__ import annotations

import argparse
import inspect
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any


def build_run_case_parser(*, description: str) -> argparse.ArgumentParser:
    """Build the standard CLI parser used by analytical `run_case.py` scripts."""
    parser = argparse.ArgumentParser(description=description)
    parser.set_defaults(show_plot=True)
    parser.add_argument(
        "--output-png",
        type=Path,
        default=None,
        help=(
            "Optional PNG output path. Defaults to the validation run directory "
            "created for this execution."
        ),
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=160,
        help="Matplotlib save DPI for the generated figure.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Maximum launcher runtime in seconds.",
    )
    parser.add_argument(
        "--solver",
        type=str,
        default=None,
        help=(
            "Optional solver variant to run for cases that expose more than one "
            "launcher backend."
        ),
    )
    parser.add_argument(
        "--show",
        dest="show_plot",
        action="store_true",
        help="Open the matplotlib window after saving the figure.",
    )
    parser.add_argument(
        "--no-show",
        dest="show_plot",
        action="store_false",
        help="Do not open the matplotlib window after saving the figure.",
    )
    return parser


def resolve_output_png(
    raw_output_png: Path | None,
    *,
    default_dir: Path,
    default_filename: str,
) -> Path:
    """Resolve the PNG output path for one runner execution."""
    if raw_output_png is None:
        return (default_dir / default_filename).resolve()
    return raw_output_png.expanduser().resolve()


def print_run_case_summary(
    *,
    saved_png: Path,
    comparison: Any,
    metric_lines: Iterable[str],
) -> None:
    """Print the standard runner summary and one case-specific metric block."""
    print(f"Saved figure: {saved_png}")
    solver_name = getattr(comparison.result, "solver_name", None)
    if solver_name:
        print(f"Solver: {solver_name}")
    print(f"Results directory: {comparison.result.out_path}")
    print(f"Postprocess directory: {comparison.result.postprocess_dir}")
    for line in metric_lines:
        print(line)


def run_case_main(
    argv: list[str] | None = None,
    *,
    description: str,
    default_figure_name: str,
    caller_file: str | Path,
    run_comparison: Callable[..., Any],
    plot_comparison: Callable[..., Path],
    build_metric_lines: Callable[[Any], Iterable[str]],
) -> None:
    """Run one analytical validation case, plot it, and print a short summary."""
    parser = build_run_case_parser(description=description)
    args = parser.parse_args(argv)
    run_signature = inspect.signature(run_comparison)
    supports_solver = "solver" in run_signature.parameters
    if args.solver is not None and not supports_solver:
        parser.error("--solver is not supported by this validation case.")

    run_kwargs = {
        "caller_file": caller_file,
        "timeout": int(args.timeout),
    }
    if supports_solver and args.solver is not None:
        run_kwargs["solver"] = str(args.solver)

    comparison = run_comparison(**run_kwargs)
    output_png = resolve_output_png(
        args.output_png,
        default_dir=comparison.result.out_path,
        default_filename=default_figure_name,
    )
    saved_png = plot_comparison(
        comparison,
        output_png=output_png,
        show_plot=bool(args.show_plot),
        dpi=int(args.dpi),
    )
    print_run_case_summary(
        saved_png=saved_png,
        comparison=comparison,
        metric_lines=build_metric_lines(comparison),
    )
