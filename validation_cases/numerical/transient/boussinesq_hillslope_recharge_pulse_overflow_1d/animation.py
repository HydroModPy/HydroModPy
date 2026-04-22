"""Animation exports for the transient hillslope pulse-overflow case."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.display.animation import (
    build_gif,
    build_mp4,
    build_plotly_slider,
)

from .comparison import HillslopeOverflowScenario


PRIMARY_COLOR = "#0f4c5c"
SECONDARY_COLOR = "#bc4b51"
ACCENT_COLOR = "#d4a373"


@dataclass(frozen=True, slots=True)
class OverflowAnimationOptions:
    """Options controlling the exported overflow animation."""

    frame_step: int = 1
    gif_duration_ms: int = 220
    export_gif: bool = True
    export_mp4: bool = False
    export_html: bool = False
    video_fps: int = 10


def _align_step_series(x_edges: np.ndarray, y_values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Trim one step series so Matplotlib always receives matching lengths."""
    x = np.asarray(x_edges, dtype=float).reshape(-1)
    y = np.asarray(y_values, dtype=float).reshape(-1)
    count = min(x.size, y.size)
    if count <= 0:
        return np.asarray([], dtype=float), np.asarray([], dtype=float)
    return x[:count], y[:count]


def _render_frame(
    scenario: HillslopeOverflowScenario,
    *,
    time_index: int,
    output_png: Path,
    dpi: int,
) -> Path:
    primary = scenario.primary
    secondary = scenario.secondary
    time_days = float(primary.elapsed_days[time_index])

    fig = plt.figure(figsize=(13.2, 8.6), dpi=dpi)
    fig.patch.set_facecolor("#f4f1ea")
    axes = fig.subplot_mosaic(
        [
            ["profile", "overflow"],
            ["timeseries", "heatmap"],
        ],
        width_ratios=[1.15, 1.0],
        height_ratios=[1.0, 1.0],
    )

    ax_profile = axes["profile"]
    ax_overflow = axes["overflow"]
    ax_timeseries = axes["timeseries"]
    ax_heatmap = axes["heatmap"]
    recharge_time_days, recharge_mm_day = _align_step_series(
        primary.elapsed_days[:-1],
        primary.recharge_mm_day,
    )

    ax_profile.plot(
        primary.x_m,
        primary.topography_profile_m,
        color="#6b705c",
        lw=2.2,
        ls="--",
        label="Topography",
    )
    ax_profile.plot(
        primary.x_m,
        primary.mean_head_profiles_m[time_index],
        color=PRIMARY_COLOR,
        lw=2.6,
        label=f"{primary.solver_name}",
    )
    if secondary is not None:
        ax_profile.plot(
            secondary.x_m,
            secondary.mean_head_profiles_m[time_index],
            color=SECONDARY_COLOR,
            lw=2.0,
            ls="--",
            label=f"{secondary.solver_name}",
        )
    ax_profile.set_title(f"Mean Head Profile at t={time_days:.1f} day")
    ax_profile.set_xlabel("x [m]")
    ax_profile.set_ylabel("Elevation [m]")
    ax_profile.grid(True, ls=":", alpha=0.35)
    ax_profile.legend(loc="best", fontsize=8.5)

    ax_overflow.plot(
        primary.x_m,
        primary.mean_saturation_excess_mm_day[time_index],
        color=PRIMARY_COLOR,
        lw=2.6,
        label=f"{primary.solver_name}",
    )
    ax_overflow.fill_between(
        primary.x_m,
        0.0,
        primary.mean_saturation_excess_mm_day[time_index],
        color=PRIMARY_COLOR,
        alpha=0.18,
    )
    if secondary is not None:
        ax_overflow.plot(
            secondary.x_m,
            secondary.mean_saturation_excess_mm_day[time_index],
            color=SECONDARY_COLOR,
            lw=2.0,
            ls="--",
            label=f"{secondary.solver_name}",
        )
    ax_overflow.axhline(
        primary.overflow_threshold_mm_day,
        color=ACCENT_COLOR,
        lw=1.1,
        ls=":",
        label="Activity threshold",
    )
    ax_overflow.set_title("Surface Overflow Profile")
    ax_overflow.set_xlabel("x [m]")
    ax_overflow.set_ylabel("Overflow [mm/day]")
    ax_overflow.grid(True, ls=":", alpha=0.35)
    ax_overflow.legend(loc="best", fontsize=8.0)

    if recharge_time_days.size != 0:
        ax_timeseries.step(
            recharge_time_days,
            recharge_mm_day,
            where="post",
            color="#7f5539",
            lw=1.8,
            label="Recharge",
        )
    ax_timeseries.axvline(time_days, color="0.25", lw=1.1, ls="--")
    ax_timeseries.set_xlabel("Time [day]")
    ax_timeseries.set_ylabel("Recharge [mm/day]", color="#7f5539")
    ax_timeseries.tick_params(axis="y", labelcolor="#7f5539")
    ax_timeseries.grid(True, ls=":", alpha=0.35)

    ax_q = ax_timeseries.twinx()
    ax_q.plot(
        primary.elapsed_days,
        primary.total_overflow_m3_day,
        color=PRIMARY_COLOR,
        lw=2.4,
        label=f"{primary.solver_name} total overflow",
    )
    if secondary is not None:
        ax_q.plot(
            secondary.elapsed_days,
            secondary.total_overflow_m3_day,
            color=SECONDARY_COLOR,
            lw=1.9,
            ls="--",
            label=f"{secondary.solver_name} total overflow",
        )
    ax_q.axvline(time_days, color="0.25", lw=1.1, ls="--")
    ax_q.set_ylabel("Integrated overflow [m3/day]", color=PRIMARY_COLOR)
    ax_q.tick_params(axis="y", labelcolor=PRIMARY_COLOR)
    handles_left, labels_left = ax_timeseries.get_legend_handles_labels()
    handles_right, labels_right = ax_q.get_legend_handles_labels()
    ax_timeseries.legend(
        handles_left + handles_right,
        labels_left + labels_right,
        loc="upper left",
        fontsize=8.0,
    )
    ax_timeseries.set_title("Recharge and Total Overflow")

    x_edges = np.concatenate(
        (
            [primary.x_m[0] - 0.5 * (primary.x_m[1] - primary.x_m[0])],
            primary.x_m[:-1] + 0.5 * np.diff(primary.x_m),
            [primary.x_m[-1] + 0.5 * (primary.x_m[-1] - primary.x_m[-2])],
        )
    )
    time_edges = np.concatenate(
        (
            [primary.elapsed_days[0] - 0.5 * (primary.elapsed_days[1] - primary.elapsed_days[0])],
            primary.elapsed_days[:-1] + 0.5 * np.diff(primary.elapsed_days),
            [
                primary.elapsed_days[-1]
                + 0.5 * (primary.elapsed_days[-1] - primary.elapsed_days[-2])
            ],
        )
    )
    heatmap = ax_heatmap.pcolormesh(
        x_edges,
        time_edges,
        primary.mean_saturation_excess_mm_day,
        shading="auto",
        cmap="magma",
    )
    ax_heatmap.axhline(time_days, color="white", lw=1.4, ls="--")
    ax_heatmap.set_title("Primary Overflow Heatmap")
    ax_heatmap.set_xlabel("x [m]")
    ax_heatmap.set_ylabel("Time [day]")
    fig.colorbar(heatmap, ax=ax_heatmap, pad=0.02, shrink=0.9, label="Overflow [mm/day]")

    fig.suptitle(
        "Boussinesq Hillslope Overflow Animation",
        fontsize=15,
        fontweight="bold",
        y=0.985,
    )
    fig.subplots_adjust(left=0.06, right=0.97, top=0.93, bottom=0.07, wspace=0.24, hspace=0.26)
    fig.savefig(output_png, bbox_inches="tight")
    plt.close(fig)
    return output_png


def build_hillslope_overflow_animation(
    scenario: HillslopeOverflowScenario,
    *,
    output_dir: Path,
    dpi: int = 160,
    options: OverflowAnimationOptions | None = None,
) -> tuple[Path | None, Path | None, Path | None, list[Path]]:
    """Render frame PNGs and optionally assemble GIF / MP4 / HTML outputs."""
    resolved_options = OverflowAnimationOptions() if options is None else options
    frame_step = max(1, int(resolved_options.frame_step))

    frame_dir = Path(output_dir).expanduser().resolve() / "_animation_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    frame_indices = list(range(0, len(scenario.primary.elapsed_days), frame_step))
    if frame_indices[-1] != len(scenario.primary.elapsed_days) - 1:
        frame_indices.append(len(scenario.primary.elapsed_days) - 1)

    frame_paths: list[Path] = []
    for frame_number, time_index in enumerate(frame_indices):
        frame_path = frame_dir / f"overflow_frame_{frame_number:03d}.png"
        frame_paths.append(
            _render_frame(
                scenario,
                time_index=int(time_index),
                output_png=frame_path,
                dpi=int(dpi),
            )
        )

    gif_path = None
    mp4_path = None
    html_path = None
    if resolved_options.export_gif:
        gif_path = build_gif(
            frame_paths=frame_paths,
            gif_path=Path(output_dir).expanduser().resolve() / "boussinesq_hillslope_overflow.gif",
            duration_ms=int(resolved_options.gif_duration_ms),
        )
    if resolved_options.export_mp4:
        mp4_path = build_mp4(
            frame_paths=frame_paths,
            mp4_path=Path(output_dir).expanduser().resolve() / "boussinesq_hillslope_overflow.mp4",
            fps=int(resolved_options.video_fps),
        )
    if resolved_options.export_html:
        html_path = build_plotly_slider(
            frame_paths=frame_paths,
            html_path=Path(output_dir).expanduser().resolve()
            / "boussinesq_hillslope_overflow_animation.html",
            show_in_browser=False,
            title="Boussinesq hillslope overflow animation",
        )
    return gif_path, mp4_path, html_path, frame_paths


__all__ = [
    "OverflowAnimationOptions",
    "build_hillslope_overflow_animation",
]
