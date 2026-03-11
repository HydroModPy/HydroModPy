"""Run the steady circular-island ocean validation case and plot the comparison."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


if __package__ is None or __package__ == "":
    # Allow `python path/to/run_case.py` by exposing the repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation_cases.analytical.steady.dupuit_circular_island_ocean_2d.comparison import (
    run_dupuit_circular_island_ocean_comparison,
)
from validation_cases.analytical.steady.dupuit_circular_island_ocean_2d.plotting import (
    plot_dupuit_circular_island_ocean_comparison,
)


DEFAULT_FIGURE_NAME = "dupuit_circular_island_ocean_2d_validation.png"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the circular-island ocean validation case and plot the result.",
    )
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


def _resolve_output_path(raw_output_png: Path | None, *, default_dir: Path) -> Path:
    if raw_output_png is None:
        return (default_dir / DEFAULT_FIGURE_NAME).resolve()
    return raw_output_png.expanduser().resolve()


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    comparison = run_dupuit_circular_island_ocean_comparison(
        caller_file=__file__,
        timeout=int(args.timeout),
    )
    output_png = _resolve_output_path(args.output_png, default_dir=comparison.result.out_path)
    saved_png = plot_dupuit_circular_island_ocean_comparison(
        comparison,
        output_png=output_png,
        show_plot=bool(args.show_plot),
        dpi=int(args.dpi),
    )

    print(f"Saved figure: {saved_png}")
    print(f"Results directory: {comparison.result.out_path}")
    print(f"Postprocess directory: {comparison.result.postprocess_dir}")
    print(f"Radial head-profile RMSE: {comparison.rms_error:.4f} m")
    print(f"Radial head-profile max abs error: {comparison.max_error:.4f} m")
    print(f"Azimuthal spread: {comparison.azimuthal_spread:.4f} m")
    print(f"Ocean head max abs error: {comparison.ocean_head_max_error:.2e} m")
    print(f"Minimum land freeboard: {comparison.land_clearance_min:.4f} m")


if __name__ == "__main__":
    main()
