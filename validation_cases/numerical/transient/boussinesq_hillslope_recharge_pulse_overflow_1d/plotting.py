"""Plotting helpers for the transient hillslope pulse-overflow case."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from .comparison import HillslopeOverflowScenario

PRIMARY_COLOR = "#0f4c5c"
SECONDARY_COLOR = "#bc4b51"
ACCENT_COLOR = "#d4a373"


@dataclass(frozen=True, slots=True)
class OverflowPlotOptions:
    """User-tunable rendering choices for the composite overflow figure."""

    snapshot_days: tuple[float, ...] = ()
    max_snapshots: int = 6
    overflow_threshold_mm_day: float | None = None


def _enable_interactive_backend(show_plot: bool) -> bool:
    if not show_plot:
        return False

    backend = str(plt.get_backend()).lower()
    if "agg" not in backend:
        return True

    for candidate in ("QtAgg", "TkAgg"):
        try:
            plt.switch_backend(candidate)
        except Exception:
            continue
        return True

    print("Figure backend is non-interactive (Agg): figure saved but could not be displayed.")
    return False


def _nearest_index(values: np.ndarray, target: float) -> int:
    return int(np.argmin(np.abs(np.asarray(values, dtype=float) - float(target))))


def select_snapshot_indices(
    elapsed_days: np.ndarray,
    *,
    requested_days: tuple[float, ...] = (),
    max_snapshots: int = 6,
    onset_day: float | None = None,
    peak_day: float | None = None,
) -> list[int]:
    """Choose one compact set of snapshot indices for the profile panel."""
    times = np.asarray(elapsed_days, dtype=float).reshape(-1)
    selected: list[int] = []

    for value in requested_days:
        index = _nearest_index(times, float(value))
        if index not in selected:
            selected.append(index)

    if selected:
        return selected[: max(1, int(max_snapshots))]

    candidates = [0, len(times) - 1]
    if onset_day is not None and np.isfinite(float(onset_day)):
        candidates.append(_nearest_index(times, float(onset_day)))
    if peak_day is not None and np.isfinite(float(peak_day)):
        candidates.append(_nearest_index(times, float(peak_day)))

    if len(times) > 2:
        interior = np.linspace(0, len(times) - 1, num=max(2, int(max_snapshots)), dtype=int)
        candidates.extend(int(value) for value in interior.tolist())

    for index in candidates:
        if index not in selected:
            selected.append(int(index))
        if len(selected) >= int(max_snapshots):
            break
    return sorted(selected)


def _build_edges(centers: np.ndarray) -> np.ndarray:
    values = np.asarray(centers, dtype=float).reshape(-1)
    if values.size == 1:
        return np.asarray([values[0] - 0.5, values[0] + 0.5], dtype=float)
    deltas = np.diff(values)
    left = values[0] - (0.5 * deltas[0])
    right = values[-1] + (0.5 * deltas[-1])
    mids = values[:-1] + (0.5 * deltas)
    return np.concatenate(([left], mids, [right]))


def _align_step_series(x_edges: np.ndarray, y_values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Trim one step series so Matplotlib always receives matching lengths."""
    x = np.asarray(x_edges, dtype=float).reshape(-1)
    y = np.asarray(y_values, dtype=float).reshape(-1)
    count = min(x.size, y.size)
    if count <= 0:
        return np.asarray([], dtype=float), np.asarray([], dtype=float)
    return x[:count], y[:count]


def _plot_metrics_card(ax, scenario: HillslopeOverflowScenario) -> None:
    ax.set_axis_off()
    primary = scenario.primary
    secondary = scenario.secondary
    lines = [
        "Transient Hillslope Overflow",
        "",
        f"Primary:   {primary.solver_label}",
        f"Backend:   {primary.runtime_backend}",
        f"Surface:   {primary.surface_interaction_model}",
        f"Onset:     {primary.onset_day:.1f} d"
        if np.isfinite(primary.onset_day)
        else "Onset:     not reached",
        f"Peak Qs:   {primary.peak_total_overflow_m3_day:.2f} m3/day",
        f"Peak len:  {primary.peak_active_length_m:.1f} m",
        f"Max h-z:   {primary.max_head_clearance_m:.3f} m",
    ]
    if secondary is not None:
        lines.extend(
            [
                "",
                f"Compare:   {secondary.solver_label}",
                f"Backend:   {secondary.runtime_backend}",
                f"Surface:   {secondary.surface_interaction_model}",
                (
                    f"Delta peak Qs: "
                    f"{primary.peak_total_overflow_m3_day - secondary.peak_total_overflow_m3_day:+.2f} m3/day"
                ),
                (
                    f"Delta onset: {primary.onset_day - secondary.onset_day:+.1f} d"
                    if np.isfinite(primary.onset_day) and np.isfinite(secondary.onset_day)
                    else "Delta onset: n/a"
                ),
            ]
        )
    elif scenario.secondary_error:
        secondary_error = str(scenario.secondary_error).strip().splitlines()[0]
        if len(secondary_error) > 88:
            secondary_error = secondary_error[:85] + "..."
        lines.extend(
            [
                "",
                f"Compare:   {scenario.secondary_solver_name or 'unknown'}",
                "Status:    failed",
                secondary_error,
            ]
        )

    ax.text(
        0.03,
        0.98,
        "\n".join(lines),
        va="top",
        ha="left",
        fontsize=10,
        family="monospace",
        bbox={
            "boxstyle": "round,pad=0.5",
            "fc": "#f7f5ef",
            "ec": "#d0c7b8",
            "alpha": 0.98,
        },
        transform=ax.transAxes,
    )


def plot_hillslope_overflow_scenario(
    scenario: HillslopeOverflowScenario,
    *,
    output_png: str | Path,
    show_plot: bool = True,
    dpi: int = 180,
    plot_options: OverflowPlotOptions | None = None,
) -> Path:
    """Save a composite figure for one or two solver runs on the same forcing."""
    options = OverflowPlotOptions() if plot_options is None else plot_options
    show_plot = _enable_interactive_backend(show_plot)
    output_path = Path(output_png).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    primary = scenario.primary
    secondary = scenario.secondary
    plot_cfg = dict(scenario.metadata.get("plot", {}))
    threshold = (
        primary.overflow_threshold_mm_day
        if options.overflow_threshold_mm_day is None
        else float(options.overflow_threshold_mm_day)
    )
    requested_snapshot_days = tuple(options.snapshot_days)
    if not requested_snapshot_days:
        requested_snapshot_days = tuple(
            float(value) for value in plot_cfg.get("default_snapshot_days", ())
        )
    max_snapshot_count = int(
        options.max_snapshots if options.max_snapshots else plot_cfg.get("max_snapshots", 6)
    )
    snapshot_indices = select_snapshot_indices(
        primary.elapsed_days,
        requested_days=requested_snapshot_days,
        max_snapshots=max_snapshot_count,
        onset_day=primary.onset_day,
        peak_day=primary.peak_overflow_day,
    )
    snapshot_colors = plt.cm.cividis(np.linspace(0.12, 0.88, len(snapshot_indices)))

    plt.style.use("default")
    fig = plt.figure(figsize=(15.4, 10.2), dpi=dpi)
    fig.patch.set_facecolor("#f4f1ea")
    axes = fig.subplot_mosaic(
        [
            ["profiles", "profiles", "card"],
            ["overflow", "overflow", "contrast"],
            ["total", "front", "front"],
        ],
        width_ratios=[1.45, 1.45, 1.0],
        height_ratios=[1.25, 1.05, 0.95],
    )

    ax_profiles = axes["profiles"]
    ax_card = axes["card"]
    ax_overflow = axes["overflow"]
    ax_contrast = axes["contrast"]
    ax_total = axes["total"]
    ax_front = axes["front"]

    for color, index in zip(snapshot_colors, snapshot_indices, strict=False):
        label = f"t={primary.elapsed_days[index]:.0f} d"
        ax_profiles.plot(
            primary.x_m,
            primary.mean_head_profiles_m[index],
            color=color,
            lw=2.4,
            label=f"{label} primary",
            zorder=3,
        )
        if secondary is not None:
            ax_profiles.plot(
                secondary.x_m,
                secondary.mean_head_profiles_m[index],
                color=color,
                lw=1.6,
                ls="--",
                label=f"{label} compare",
                zorder=4,
            )
    ax_profiles.plot(
        primary.x_m,
        primary.topography_profile_m,
        color="#6b705c",
        lw=2.2,
        ls="--",
        label="Topography",
        zorder=2,
    )
    ax_profiles.fill_between(
        primary.x_m,
        primary.topography_profile_m,
        np.min(primary.mean_head_profiles_m) - 0.5,
        color="#e9dcc9",
        alpha=0.45,
        zorder=1,
    )
    profile_padding = float(plot_cfg.get("profile_limit_padding_m", 0.4))
    ax_profiles.set_xlim(float(primary.x_m[0]), float(primary.x_m[-1]))
    ax_profiles.set_ylim(
        float(np.min(primary.mean_head_profiles_m) - profile_padding),
        float(np.max(primary.topography_profile_m) + profile_padding),
    )
    ax_profiles.set_title("Selected Mean Head Profiles", fontsize=13)
    ax_profiles.set_xlabel("x [m]")
    ax_profiles.set_ylabel("Elevation [m]")
    ax_profiles.grid(True, ls=":", alpha=0.35)
    ax_profiles.legend(loc="best", ncol=2, fontsize=8.5)

    x_edges = _build_edges(primary.x_m)
    time_centers = np.asarray(primary.elapsed_days, dtype=float)
    time_edges = _build_edges(time_centers)
    overflow_artist = ax_overflow.pcolormesh(
        x_edges,
        time_edges,
        primary.mean_saturation_excess_mm_day,
        shading="auto",
        cmap="magma",
    )
    fig.colorbar(
        overflow_artist,
        ax=ax_overflow,
        pad=0.01,
        shrink=0.9,
        label="Surface flux [mm/day]",
    )
    ax_overflow.contour(
        primary.x_m,
        time_centers,
        primary.mean_saturation_excess_mm_day,
        levels=[threshold],
        colors="white",
        linewidths=0.8,
        linestyles="--",
    )
    ax_overflow.set_title(f"Primary Surface-Overflow Heatmap (threshold {threshold:.3g} mm/day)")
    ax_overflow.set_xlabel("x [m]")
    ax_overflow.set_ylabel("Time [day]")

    if secondary is not None:
        contrast_field = (
            primary.mean_saturation_excess_mm_day - secondary.mean_saturation_excess_mm_day
        )
        contrast_artist = ax_contrast.pcolormesh(
            x_edges,
            time_edges,
            contrast_field,
            shading="auto",
            cmap="coolwarm",
        )
        fig.colorbar(
            contrast_artist,
            ax=ax_contrast,
            pad=0.02,
            shrink=0.9,
            label="Primary - compare [mm/day]",
        )
        ax_contrast.set_title("Surface-Flux Difference")
    else:
        contrast_artist = ax_contrast.pcolormesh(
            x_edges,
            time_edges,
            primary.mean_head_clearance_m,
            shading="auto",
            cmap="RdBu_r",
        )
        fig.colorbar(
            contrast_artist,
            ax=ax_contrast,
            pad=0.02,
            shrink=0.9,
            label="h - z_top [m]",
        )
        ax_contrast.contour(
            primary.x_m,
            time_centers,
            primary.mean_head_clearance_m,
            levels=[0.0],
            colors="black",
            linewidths=0.9,
        )
        ax_contrast.set_title("Head Clearance to Surface")
    ax_contrast.set_xlabel("x [m]")
    ax_contrast.set_ylabel("Time [day]")

    recharge_edges = primary.elapsed_days
    recharge_time_days, recharge_mm_day = _align_step_series(
        recharge_edges[:-1],
        primary.recharge_mm_day,
    )
    ax_total.set_facecolor("#fcfbf7")
    if recharge_time_days.size != 0:
        ax_total.fill_between(
            recharge_time_days,
            recharge_mm_day,
            step="post",
            color="#d6ccc2",
            alpha=0.8,
            label="Recharge",
        )
        ax_total.step(
            recharge_time_days,
            recharge_mm_day,
            where="post",
            color="#7f5539",
            lw=1.6,
        )
    ax_total.set_xlabel("Time [day]")
    ax_total.set_ylabel("Recharge [mm/day]", color="#7f5539")
    ax_total.tick_params(axis="y", labelcolor="#7f5539")
    ax_total.grid(True, ls=":", alpha=0.35)

    ax_total_q = ax_total.twinx()
    ax_total_q.plot(
        primary.elapsed_days,
        primary.total_overflow_m3_day,
        color=PRIMARY_COLOR,
        lw=2.4,
        label="Primary total overflow",
    )
    if secondary is not None:
        ax_total_q.plot(
            secondary.elapsed_days,
            secondary.total_overflow_m3_day,
            color=SECONDARY_COLOR,
            lw=2.0,
            ls="--",
            label="Compare total overflow",
        )
    if np.isfinite(primary.onset_day):
        ax_total.axvline(primary.onset_day, color=PRIMARY_COLOR, lw=1.0, ls=":")
    ax_total.axvline(primary.peak_overflow_day, color=PRIMARY_COLOR, lw=1.0, ls="--")
    ax_total_q.set_ylabel("Integrated overflow [m3/day]", color=PRIMARY_COLOR)
    ax_total_q.tick_params(axis="y", labelcolor=PRIMARY_COLOR)
    handles_left, labels_left = ax_total.get_legend_handles_labels()
    handles_right, labels_right = ax_total_q.get_legend_handles_labels()
    ax_total.legend(
        handles_left + handles_right, labels_left + labels_right, loc="upper left", fontsize=8.5
    )
    ax_total.set_title("Recharge Pulses and Integrated Surface Release")

    ax_front.plot(
        primary.elapsed_days,
        primary.overflow_front_x_m,
        color=PRIMARY_COLOR,
        lw=2.4,
        label="Primary front",
    )
    ax_front.plot(
        primary.elapsed_days,
        primary.overflow_centroid_x_m,
        color=PRIMARY_COLOR,
        lw=1.6,
        ls="--",
        label="Primary centroid",
    )
    if secondary is not None:
        ax_front.plot(
            secondary.elapsed_days,
            secondary.overflow_front_x_m,
            color=SECONDARY_COLOR,
            lw=2.0,
            label="Compare front",
        )
        ax_front.plot(
            secondary.elapsed_days,
            secondary.overflow_centroid_x_m,
            color=SECONDARY_COLOR,
            lw=1.4,
            ls="--",
            label="Compare centroid",
        )
    ax_front.set_xlabel("Time [day]")
    ax_front.set_ylabel("Front / centroid x [m]")
    ax_front.grid(True, ls=":", alpha=0.35)
    ax_front_len = ax_front.twinx()
    ax_front_len.fill_between(
        primary.elapsed_days,
        primary.active_overflow_length_m,
        color=ACCENT_COLOR,
        alpha=0.22,
        label="Primary active length",
    )
    ax_front_len.plot(
        primary.elapsed_days,
        primary.active_overflow_length_m,
        color=ACCENT_COLOR,
        lw=1.8,
    )
    if secondary is not None:
        ax_front_len.plot(
            secondary.elapsed_days,
            secondary.active_overflow_length_m,
            color=SECONDARY_COLOR,
            lw=1.4,
            ls=":",
        )
    ax_front_len.set_ylabel("Active length [m]", color=ACCENT_COLOR)
    ax_front_len.tick_params(axis="y", labelcolor=ACCENT_COLOR)
    handles_front, labels_front = ax_front.get_legend_handles_labels()
    ax_front.legend(handles_front, labels_front, loc="upper left", fontsize=8.5)
    ax_front.set_title("Overflow Footprint Dynamics")

    _plot_metrics_card(ax_card, scenario)

    fig.suptitle(
        "Boussinesq Hillslope Recharge-Pulse Overflow",
        fontsize=16,
        fontweight="bold",
        y=0.985,
    )
    fig.subplots_adjust(left=0.055, right=0.96, top=0.94, bottom=0.06, wspace=0.25, hspace=0.28)
    fig.savefig(output_path, bbox_inches="tight")

    if show_plot:
        plt.show(block=True)
    plt.close(fig)
    return output_path


__all__ = [
    "OverflowPlotOptions",
    "plot_hillslope_overflow_scenario",
    "select_snapshot_indices",
]
