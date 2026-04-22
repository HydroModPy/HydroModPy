"""CLI entrypoint for the transient hillslope recharge-pulse overflow case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.shared.cli import (
    apply_output_root_override,
    build_run_case_parser,
    resolve_output_png,
)

from .animation import (
    OverflowAnimationOptions,
    build_hillslope_overflow_animation,
)
from .comparison import run_hillslope_overflow_scenario
from .plotting import OverflowPlotOptions, plot_hillslope_overflow_scenario
from .runtime_boussinesq import DEFAULT_SOLVER

DEFAULT_FIGURE_NAME = "boussinesq_hillslope_recharge_pulse_overflow_1d.png"


def _build_parser():
    parser = build_run_case_parser(
        description=(
            "Run the transient hillslope pulse-overflow case and generate one "
            "composite figure for the selected Boussinesq runtime."
        )
    )
    parser.add_argument(
        "--compare-solver",
        type=str,
        default=None,
        help="Optional second solver to run on the same case for figure overlays.",
    )
    parser.add_argument(
        "--forcing-preset",
        type=str,
        default=None,
        help="Optional forcing preset defined by the case metadata (for example strong, extreme).",
    )
    parser.add_argument(
        "--forcing-scale",
        type=float,
        default=1.0,
        help="Uniform multiplier applied to the recharge chronicle.",
    )
    parser.add_argument(
        "--east-head",
        type=float,
        default=None,
        help="Optional downstream fixed head override in meters.",
    )
    parser.add_argument(
        "--initial-head",
        type=float,
        default=None,
        help="Optional initial head override in meters.",
    )
    parser.add_argument(
        "--dt-days",
        type=float,
        default=None,
        help="Optional transient step length override in days.",
    )
    parser.add_argument(
        "--runtime-max-iterations",
        type=int,
        default=None,
        help="Optional nonlinear iteration budget override for the selected runtime(s).",
    )
    parser.add_argument(
        "--runtime-tol-residual-inf",
        type=float,
        default=None,
        help="Optional residual tolerance override for the selected runtime(s).",
    )
    parser.add_argument(
        "--snapshot-days",
        type=float,
        nargs="*",
        default=(),
        help="Optional explicit profile snapshot days. Defaults to auto-selected milestones.",
    )
    parser.add_argument(
        "--max-snapshots",
        type=int,
        default=6,
        help="Maximum number of profile snapshots drawn on the top panel.",
    )
    parser.add_argument(
        "--overflow-threshold-mm-day",
        type=float,
        default=None,
        help="Override the active-overflow threshold used for footprint diagnostics.",
    )
    parser.add_argument(
        "--gif",
        action="store_true",
        help="Export an animated GIF showing the temporal evolution.",
    )
    parser.add_argument(
        "--mp4",
        action="store_true",
        help="Export an MP4 video showing the temporal evolution.",
    )
    parser.add_argument(
        "--html-animation",
        action="store_true",
        help="Export a browser-friendly HTML slider animation from the rendered frames.",
    )
    parser.add_argument(
        "--frame-step",
        type=int,
        default=1,
        help="Keep one animation frame every N simulated timesteps.",
    )
    parser.add_argument(
        "--gif-duration-ms",
        type=int,
        default=220,
        help="Per-frame duration used by the exported GIF animation.",
    )
    parser.add_argument(
        "--video-fps",
        type=int,
        default=10,
        help="Frames per second used by the exported MP4 video.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    apply_output_root_override(args.output_root)

    scenario = run_hillslope_overflow_scenario(
        caller_file=Path(__file__),
        timeout=int(args.timeout),
        solver=(DEFAULT_SOLVER if args.solver is None else str(args.solver)),
        compare_solver=args.compare_solver,
        overflow_threshold_mm_day=args.overflow_threshold_mm_day,
        forcing_preset=args.forcing_preset,
        forcing_scale=float(args.forcing_scale),
        east_head_m=args.east_head,
        initial_head_m=args.initial_head,
        dt_days=args.dt_days,
        runtime_max_iterations=args.runtime_max_iterations,
        runtime_tol_residual_inf=args.runtime_tol_residual_inf,
    )
    output_png = resolve_output_png(
        args.output_png,
        default_dir=scenario.primary.result.out_path,
        default_filename=DEFAULT_FIGURE_NAME,
    )
    saved_png = plot_hillslope_overflow_scenario(
        scenario,
        output_png=output_png,
        show_plot=bool(args.show_plot),
        dpi=int(args.dpi),
        plot_options=OverflowPlotOptions(
            snapshot_days=tuple(float(value) for value in args.snapshot_days),
            max_snapshots=int(args.max_snapshots),
            overflow_threshold_mm_day=args.overflow_threshold_mm_day,
        ),
    )
    gif_path = None
    mp4_path = None
    html_path = None
    if bool(args.gif) or bool(args.mp4) or bool(args.html_animation):
        gif_path, mp4_path, html_path, _ = build_hillslope_overflow_animation(
            scenario,
            output_dir=scenario.primary.result.out_path,
            dpi=max(120, int(args.dpi)),
            options=OverflowAnimationOptions(
                frame_step=max(1, int(args.frame_step)),
                gif_duration_ms=int(args.gif_duration_ms),
                export_gif=bool(args.gif),
                export_mp4=bool(args.mp4),
                export_html=bool(args.html_animation),
                video_fps=max(1, int(args.video_fps)),
            ),
        )

    print(f"Saved figure: {saved_png}")
    print(f"Primary solver: {scenario.primary.solver_name}")
    print(f"Primary results directory: {scenario.primary.result.out_path}")
    print(
        "Primary summary: "
        f"onset={scenario.primary.onset_day:.2f} d, "
        f"peak_qs={scenario.primary.peak_total_overflow_m3_day:.2f} m3/day, "
        f"peak_length={scenario.primary.peak_active_length_m:.1f} m, "
        f"max_h_minus_top={scenario.primary.max_head_clearance_m:.3f} m"
    )
    if scenario.secondary is not None:
        print(f"Compare solver: {scenario.secondary.solver_name}")
        print(f"Compare results directory: {scenario.secondary.result.out_path}")
        print(
            "Compare summary: "
            f"onset={scenario.secondary.onset_day:.2f} d, "
            f"peak_qs={scenario.secondary.peak_total_overflow_m3_day:.2f} m3/day, "
            f"peak_length={scenario.secondary.peak_active_length_m:.1f} m, "
            f"max_h_minus_top={scenario.secondary.max_head_clearance_m:.3f} m"
        )
    elif scenario.secondary_error:
        print(
            "Compare solver failed: "
            f"{scenario.secondary_solver_name or args.compare_solver or '<unknown>'}"
        )
        print(str(scenario.secondary_error))
    if gif_path is not None:
        print(f"Saved GIF: {gif_path}")
    if mp4_path is not None:
        print(f"Saved MP4: {mp4_path}")
    if html_path is not None:
        print(f"Saved HTML animation: {html_path}")


if __name__ == "__main__":
    main()
