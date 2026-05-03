"""Shared comparison and plotting helpers for transient analytical 1D cases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from validation_cases.shared import (
    ValidationRunResult,
    load_case_config,
    load_case_metadata,
    load_case_tolerances,
    load_time_series_fields,
    max_abs_error,
    rmse,
)

SECONDS_PER_DAY = 86400.0


def _resolve_mesh_bundle_dir_for_solver(
    *,
    case_dir: Path,
    metadata: dict,
    solver_name: str | None,
) -> Path | None:
    """Return the external mesh bundle for solvers that declare ``[mesh_input]``."""

    normalized_solver = str(solver_name or "").strip().lower()
    config_files = metadata.get("config_files")
    if normalized_solver == "" or not isinstance(config_files, dict):
        return None
    config_name = str(config_files.get(normalized_solver, "")).strip()
    if config_name == "":
        return None

    config_payload = load_case_config(case_dir, config_name)
    mesh_input = config_payload.get("mesh_input")
    if not isinstance(mesh_input, dict):
        return None
    bundle_dir_raw = str(mesh_input.get("bundle_dir", "")).strip()
    if bundle_dir_raw == "":
        return None
    bundle_dir = Path(bundle_dir_raw).expanduser()
    if not bundle_dir.is_absolute():
        bundle_dir = (case_dir / bundle_dir).resolve()
    return bundle_dir


@dataclass(frozen=True, slots=True)
class TransientProfileOutputs:
    """Canonical payload returned by :func:`load_transient_profile_outputs`."""

    metadata: dict
    tolerances: dict
    observable_name: str
    period_indices: np.ndarray
    heads: np.ndarray
    dt_seconds: float
    elapsed_seconds: np.ndarray | None = None


@dataclass(frozen=True, slots=True)
class TransientHead1DComparison:
    """Canonical payload used by transient 1D validation cases and plots."""

    result: ValidationRunResult
    metadata: dict
    tolerances: dict
    observable_name: str
    period_indices: np.ndarray
    elapsed_seconds: np.ndarray
    elapsed_days: np.ndarray
    period_start_seconds: np.ndarray
    heads: np.ndarray
    x: np.ndarray
    profile_axis: int
    numerical_profiles: np.ndarray
    analytical_profiles: np.ndarray
    residual_profiles: np.ndarray
    monitor_positions: np.ndarray
    monitor_indices: np.ndarray
    numerical_monitor_series: np.ndarray
    analytical_monitor_series: np.ndarray
    space_time_rmse: float
    space_time_max_error: float
    final_profile_rmse: float
    final_profile_max_error: float
    row_spread: float

    @property
    def final_elapsed_days(self) -> float:
        return float(self.elapsed_days[-1])


def select_nearest_indices(values, targets) -> np.ndarray:
    """Return unique nearest indices from one monotonic axis to one target list."""
    values_arr = np.asarray(values, dtype=float).reshape(-1)
    targets_arr = np.asarray(targets, dtype=float).reshape(-1)
    if values_arr.size == 0:
        raise ValueError("values cannot be empty")
    indices = [int(np.argmin(np.abs(values_arr - float(target)))) for target in targets_arr]
    return np.asarray(sorted(set(indices)), dtype=int)


def build_monitor_series(
    *,
    x: np.ndarray,
    profiles: np.ndarray,
    monitor_positions,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample one profile matrix at the monitor positions nearest to the requested x values."""
    x_arr = np.asarray(x, dtype=float).reshape(-1)
    monitor_positions_arr = np.asarray(monitor_positions, dtype=float).reshape(-1)
    if monitor_positions_arr.size == 0:
        return (
            np.asarray([], dtype=float),
            np.asarray([], dtype=int),
            np.empty((profiles.shape[0], 0), dtype=float),
        )
    monitor_indices = np.asarray(
        [int(np.argmin(np.abs(x_arr - float(position)))) for position in monitor_positions_arr],
        dtype=int,
    )
    sampled = np.asarray(profiles[:, monitor_indices], dtype=float)
    return x_arr[monitor_indices], monitor_indices, sampled


def load_transient_profile_outputs(
    *,
    case_dir: Path,
    result: ValidationRunResult,
    metadata: dict | None = None,
    tolerances: dict | None = None,
    solver: str | None = None,
) -> TransientProfileOutputs:
    """Load one transient `watertable_elevation` dictionary and validate its shape."""
    case_metadata = load_case_metadata(case_dir) if metadata is None else metadata
    solver_name = str(getattr(result, "solver_name", "")).strip().lower() or solver
    case_tolerances = (
        load_case_tolerances(case_dir, solver=solver) if tolerances is None else tolerances
    )

    output_cfg = dict(case_metadata.get("output", {}))
    time_cfg = dict(case_metadata.get("time", {}))
    observable_name = str(output_cfg.get("observable_name", "watertable_elevation"))

    expected_spatial_shape_by_solver = output_cfg.get("expected_spatial_shape_by_solver", {})
    expected_spatial_shape_raw = ()
    if (
        isinstance(expected_spatial_shape_by_solver, dict)
        and solver_name in expected_spatial_shape_by_solver
    ):
        expected_spatial_shape_raw = tuple(expected_spatial_shape_by_solver[solver_name])
    else:
        expected_spatial_shape_raw = tuple(output_cfg.get("expected_spatial_shape", ()))

    reference_cfg = dict(case_metadata.get("reference", {}))
    mesh_bundle_dir = _resolve_mesh_bundle_dir_for_solver(
        case_dir=case_dir,
        metadata=case_metadata,
        solver_name=solver_name,
    )
    period_indices, heads = load_time_series_fields(
        postprocess_dir=result.postprocess_dir,
        store=result.store,
        sim_id=result.sim_id,
        observable_name=observable_name,
        expected_spatial_shape=expected_spatial_shape_raw or None,
        mesh_bundle_dir=mesh_bundle_dir,
        x_min_m=reference_cfg.get("xmin"),
        x_max_m=reference_cfg.get("xmax"),
        y_min_m=reference_cfg.get("ymin"),
        y_max_m=reference_cfg.get("ymax"),
    )

    expected_periods_by_solver = output_cfg.get("expected_periods_by_solver", {})
    expected_periods = 0
    if isinstance(expected_periods_by_solver, dict) and solver_name in expected_periods_by_solver:
        expected_periods = int(expected_periods_by_solver[solver_name])
    else:
        expected_periods = int(output_cfg.get("expected_periods", 0))
    if expected_periods > 0:
        assert heads.shape[0] == expected_periods, (
            f"Unexpected number of periods for {observable_name}: {heads.shape[0]} != {expected_periods}"
        )

    expected_spatial_shape_by_solver = output_cfg.get("expected_spatial_shape_by_solver", {})
    expected_spatial_shape = ()
    if (
        isinstance(expected_spatial_shape_by_solver, dict)
        and solver_name in expected_spatial_shape_by_solver
    ):
        expected_spatial_shape = tuple(expected_spatial_shape_by_solver[solver_name])
    else:
        expected_spatial_shape = tuple(output_cfg.get("expected_spatial_shape", ()))
    if expected_spatial_shape:
        assert tuple(heads.shape[1:]) == expected_spatial_shape, (
            f"Unexpected spatial shape for {observable_name}: "
            f"{tuple(heads.shape[1:])} != {expected_spatial_shape}"
        )

    dt_seconds = float(time_cfg["dt_seconds"])
    period_indices_arr = np.asarray(period_indices, dtype=float)
    elapsed_seconds = (period_indices_arr + 1.0) * dt_seconds
    return TransientProfileOutputs(
        metadata=case_metadata,
        tolerances=case_tolerances,
        observable_name=observable_name,
        period_indices=period_indices_arr,
        heads=np.asarray(heads, dtype=float),
        dt_seconds=dt_seconds,
        elapsed_seconds=elapsed_seconds,
    )


def build_transient_head_comparison(
    *,
    result: ValidationRunResult,
    case_dir: Path,
    analytical_profiles: np.ndarray,
    loaded_outputs: TransientProfileOutputs | None = None,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> TransientHead1DComparison:
    """Build one transient comparison payload from already computed analytical profiles."""
    loaded = (
        loaded_outputs
        if loaded_outputs is not None
        else load_transient_profile_outputs(
            case_dir=case_dir,
            result=result,
            metadata=metadata,
            tolerances=tolerances,
        )
    )
    case_metadata = loaded.metadata
    case_tolerances = loaded.tolerances
    observable_name = loaded.observable_name
    period_indices = loaded.period_indices
    heads = loaded.heads
    dt_seconds = loaded.dt_seconds

    reference_cfg = dict(case_metadata.get("reference", {}))
    plot_cfg = dict(case_metadata.get("plot", {}))
    profile_axis = int(reference_cfg.get("profile_axis", 0))
    numerical_profiles = np.asarray(heads.mean(axis=profile_axis + 1), dtype=float)
    analytical_profiles_arr = np.asarray(analytical_profiles, dtype=float)
    if analytical_profiles_arr.shape != numerical_profiles.shape:
        raise ValueError(
            f"Analytical profile shape {analytical_profiles_arr.shape} "
            f"does not match numerical profile shape {numerical_profiles.shape}."
        )

    elapsed_seconds = (period_indices.astype(float) + 1.0) * float(dt_seconds)
    period_start_seconds = period_indices.astype(float) * float(dt_seconds)
    x = np.linspace(
        float(reference_cfg["xmin"]),
        float(reference_cfg["xmax"]),
        numerical_profiles.shape[1],
        dtype=float,
    )
    residual_profiles = np.asarray(numerical_profiles - analytical_profiles_arr, dtype=float)

    monitor_positions, monitor_indices, numerical_monitor_series = build_monitor_series(
        x=x,
        profiles=numerical_profiles,
        monitor_positions=plot_cfg.get("monitor_positions_m", ()),
    )
    _, _, analytical_monitor_series = build_monitor_series(
        x=x,
        profiles=analytical_profiles_arr,
        monitor_positions=plot_cfg.get("monitor_positions_m", ()),
    )

    return TransientHead1DComparison(
        result=result,
        metadata=case_metadata,
        tolerances=case_tolerances,
        observable_name=observable_name,
        period_indices=period_indices,
        elapsed_seconds=elapsed_seconds,
        elapsed_days=elapsed_seconds / SECONDS_PER_DAY,
        period_start_seconds=period_start_seconds,
        heads=heads,
        x=x,
        profile_axis=profile_axis,
        numerical_profiles=numerical_profiles,
        analytical_profiles=analytical_profiles_arr,
        residual_profiles=residual_profiles,
        monitor_positions=monitor_positions,
        monitor_indices=monitor_indices,
        numerical_monitor_series=numerical_monitor_series,
        analytical_monitor_series=analytical_monitor_series,
        space_time_rmse=rmse(numerical_profiles, analytical_profiles_arr),
        space_time_max_error=max_abs_error(numerical_profiles, analytical_profiles_arr),
        final_profile_rmse=rmse(numerical_profiles[-1], analytical_profiles_arr[-1]),
        final_profile_max_error=max_abs_error(numerical_profiles[-1], analytical_profiles_arr[-1]),
        row_spread=float(np.max(np.std(heads, axis=profile_axis + 1))),
    )


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


def plot_transient_head_1d_comparison(
    comparison: TransientHead1DComparison,
    *,
    output_png: str | Path,
    title: str,
    parameter_lines: tuple[str, ...] | list[str],
    profile_times_days,
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save and optionally display one transient comparison figure."""
    show_plot = _enable_interactive_backend(show_plot)
    output_path = Path(output_png).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    plot_cfg = dict(comparison.metadata.get("plot", {}))
    tolerance_cfg = dict(comparison.tolerances.get("space_time", {}))
    profile_indices = select_nearest_indices(comparison.elapsed_days, profile_times_days)
    color_positions = np.linspace(0.08, 0.92, max(profile_indices.size, 2))
    colors = plt.cm.cividis(color_positions)

    fig = plt.figure(figsize=(12.2, 8.4), dpi=dpi)
    grid = fig.add_gridspec(2, 2, height_ratios=(2.2, 1.45), hspace=0.34, wspace=0.24)
    ax_profiles = fig.add_subplot(grid[0, :])
    ax_monitors = fig.add_subplot(grid[1, 0])
    ax_residual = fig.add_subplot(grid[1, 1])

    for color, profile_index in zip(colors, profile_indices, strict=False):
        label = f"t={comparison.elapsed_days[profile_index]:.1f} d"
        ax_profiles.plot(
            comparison.x,
            comparison.analytical_profiles[profile_index],
            color=color,
            lw=2.0,
            label=label,
            zorder=2,
        )
        ax_profiles.scatter(
            comparison.x,
            comparison.numerical_profiles[profile_index],
            s=20,
            color=color,
            edgecolors="white",
            linewidths=0.5,
            zorder=3,
        )
    ax_profiles.set_title("Profiles at selected times")
    ax_profiles.set_xlabel("x [m]")
    ax_profiles.set_ylabel("Head [m]")
    ax_profiles.grid(True, ls=":", alpha=0.4)
    ax_profiles.legend(loc="best", ncol=min(4, max(1, profile_indices.size)))
    ax_profiles.text(
        0.01,
        0.02,
        "Solid lines: analytical   Markers: numerical",
        transform=ax_profiles.transAxes,
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.24", "fc": "white", "ec": "0.80", "alpha": 0.92},
    )

    if comparison.monitor_positions.size > 0:
        monitor_colors = plt.cm.viridis(np.linspace(0.15, 0.85, comparison.monitor_positions.size))
        for index, (position, color) in enumerate(
            zip(comparison.monitor_positions, monitor_colors, strict=False)
        ):
            ax_monitors.plot(
                comparison.elapsed_days,
                comparison.analytical_monitor_series[:, index],
                color=color,
                lw=1.8,
                label=f"x={position:.0f} m",
                zorder=2,
            )
            ax_monitors.scatter(
                comparison.elapsed_days,
                comparison.numerical_monitor_series[:, index],
                s=16,
                color=color,
                edgecolors="white",
                linewidths=0.4,
                zorder=3,
            )
    ax_monitors.set_title("Monitor-point traces")
    ax_monitors.set_xlabel("Time [day]")
    ax_monitors.set_ylabel("Head [m]")
    ax_monitors.grid(True, ls=":", alpha=0.4)
    if comparison.monitor_positions.size > 0:
        ax_monitors.legend(loc="best")
    ax_monitors.text(
        0.01,
        0.02,
        "Solid lines: analytical   Markers: numerical",
        transform=ax_monitors.transAxes,
        fontsize=8.5,
        bbox={"boxstyle": "round,pad=0.24", "fc": "white", "ec": "0.80", "alpha": 0.92},
    )

    residual_vmax = float(np.max(np.abs(comparison.residual_profiles)))
    if residual_vmax <= 0.0:
        residual_vmax = 1e-9
    image = ax_residual.imshow(
        comparison.residual_profiles,
        aspect="auto",
        origin="lower",
        extent=[
            float(comparison.x[0]),
            float(comparison.x[-1]),
            float(comparison.elapsed_days[0]),
            float(comparison.elapsed_days[-1]),
        ],
        cmap="coolwarm",
        vmin=-residual_vmax,
        vmax=residual_vmax,
    )
    ax_residual.set_title("Residual heatmap (numerical - analytical)")
    ax_residual.set_xlabel("x [m]")
    ax_residual.set_ylabel("Time [day]")
    ax_residual.grid(False)
    colorbar = fig.colorbar(image, ax=ax_residual, fraction=0.046, pad=0.04)
    colorbar.set_label("Residual [m]")

    max_abs_tol = float(tolerance_cfg.get("max_abs_error", 0.0))
    footer_lines = list(parameter_lines)
    footer_lines.append(
        "space-time RMSE="
        f"{comparison.space_time_rmse:.4f} m   "
        f"space-time max abs={comparison.space_time_max_error:.4f} m   "
        f"final-profile RMSE={comparison.final_profile_rmse:.4f} m   "
        f"row spread={comparison.row_spread:.2e} m"
    )
    if max_abs_tol > 0.0:
        footer_lines.append(f"configured max-abs tolerance={max_abs_tol:.4f} m")
    if plot_cfg.get("monitor_positions_m"):
        footer_lines.append(
            "monitor positions="
            + ", ".join(f"{float(position):.0f} m" for position in plot_cfg["monitor_positions_m"])
        )

    fig.suptitle(title, fontsize=13)
    fig.text(
        0.5,
        0.01,
        "\n".join(footer_lines),
        ha="center",
        va="bottom",
        fontsize=9,
        family="monospace",
        bbox={"boxstyle": "round,pad=0.32", "fc": "white", "ec": "0.75", "alpha": 0.95},
    )
    fig.subplots_adjust(left=0.07, right=0.96, bottom=0.17, top=0.92, wspace=0.24, hspace=0.34)
    fig.savefig(output_path, bbox_inches="tight")

    if show_plot:
        plt.show(block=True)
    plt.close(fig)
    return output_path


@dataclass(frozen=True, slots=True)
class TransientRadialDrawdownComparison:
    """Canonical payload for transient radial drawdown validation cases."""

    result: ValidationRunResult
    metadata: dict
    tolerances: dict
    observable_name: str
    period_indices: np.ndarray
    elapsed_seconds: np.ndarray
    elapsed_days: np.ndarray
    x_centers: np.ndarray
    y_centers: np.ndarray
    base_head_m: float
    monitor_radii_m: np.ndarray
    azimuth_labels: tuple[str, ...]
    sample_indices: np.ndarray
    numerical_drawdown_mean: np.ndarray
    analytical_drawdown: np.ndarray
    numerical_drawdown_by_azimuth: np.ndarray
    residual_drawdown: np.ndarray
    space_time_rmse: float
    space_time_max_error: float
    final_time_rmse: float
    final_time_max_error: float
    azimuthal_spread: float

    @property
    def final_elapsed_days(self) -> float:
        return float(self.elapsed_days[-1])


def build_uniform_axis_centers(*, minimum: float, maximum: float, count: int) -> np.ndarray:
    """Return cell-center coordinates for one uniform axis."""
    if int(count) <= 0:
        raise ValueError("count must be > 0")
    span = float(maximum) - float(minimum)
    spacing = span / float(count)
    return float(minimum) + (np.arange(int(count), dtype=float) + 0.5) * spacing


def extract_radial_monitor_series(
    *,
    heads: np.ndarray,
    x_centers: np.ndarray,
    y_centers: np.ndarray,
    center_x: float,
    center_y: float,
    monitor_offsets_cells,
) -> tuple[np.ndarray, tuple[str, ...], np.ndarray, np.ndarray]:
    """Sample one 2D transient head cube at cardinal points around one center cell."""
    heads_arr = np.asarray(heads, dtype=float)
    if heads_arr.ndim != 3:
        raise ValueError(f"heads must be a 3D array [time, row, col], got shape {heads_arr.shape}")

    x_arr = np.asarray(x_centers, dtype=float).reshape(-1)
    y_arr = np.asarray(y_centers, dtype=float).reshape(-1)
    offsets = np.asarray(monitor_offsets_cells, dtype=int).reshape(-1)
    if offsets.size == 0:
        raise ValueError("monitor_offsets_cells cannot be empty")
    if np.any(offsets <= 0):
        raise ValueError("monitor_offsets_cells must contain strictly positive integers")

    center_col = int(np.argmin(np.abs(x_arr - float(center_x))))
    center_row = int(np.argmin(np.abs(y_arr - float(center_y))))
    azimuth_labels = ("east", "west", "north", "south")
    sample_indices = np.empty((offsets.size, len(azimuth_labels), 2), dtype=int)
    sampled_heads = np.empty((heads_arr.shape[0], offsets.size, len(azimuth_labels)), dtype=float)
    sample_radii = np.empty((offsets.size, len(azimuth_labels)), dtype=float)

    for offset_index, offset in enumerate(offsets):
        candidates = (
            (center_row, center_col + int(offset)),
            (center_row, center_col - int(offset)),
            (center_row + int(offset), center_col),
            (center_row - int(offset), center_col),
        )
        for azimuth_index, (row, col) in enumerate(candidates):
            if row < 0 or row >= y_arr.size or col < 0 or col >= x_arr.size:
                raise ValueError(
                    f"monitor offset {int(offset)} leaves the grid bounds around center "
                    f"(row={center_row}, col={center_col})."
                )
            sample_indices[offset_index, azimuth_index] = (row, col)
            sampled_heads[:, offset_index, azimuth_index] = heads_arr[:, row, col]
            sample_radii[offset_index, azimuth_index] = float(
                np.hypot(x_arr[col] - float(center_x), y_arr[row] - float(center_y))
            )

    monitor_radii = sample_radii.mean(axis=1)
    return monitor_radii, azimuth_labels, sample_indices, sampled_heads


def plot_transient_radial_drawdown_comparison(
    comparison: TransientRadialDrawdownComparison,
    *,
    output_png: str | Path,
    title: str,
    parameter_lines: tuple[str, ...] | list[str],
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save and optionally display one figure for radial transient drawdown comparisons."""
    show_plot = _enable_interactive_backend(show_plot)
    output_path = Path(output_png).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    space_time_tol = dict(comparison.tolerances.get("space_time", {}))
    figure = plt.figure(figsize=(12.4, 8.6), dpi=dpi)
    grid = figure.add_gridspec(2, 2, height_ratios=(2.1, 1.2), hspace=0.35, wspace=0.28)
    ax_series = figure.add_subplot(grid[0, :])
    ax_residual = figure.add_subplot(grid[1, 0])
    ax_azimuth = figure.add_subplot(grid[1, 1])

    radii_colors = plt.cm.viridis(np.linspace(0.15, 0.9, max(comparison.monitor_radii_m.size, 2)))
    time_days = np.asarray(comparison.elapsed_days, dtype=float)
    positive_time = np.maximum(time_days, np.finfo(float).eps)

    for radius_index, (radius, color) in enumerate(
        zip(comparison.monitor_radii_m, radii_colors, strict=False)
    ):
        label = f"r={float(radius):.1f} m"
        ax_series.semilogx(
            positive_time,
            comparison.analytical_drawdown[:, radius_index],
            color=color,
            lw=2.0,
            label=label,
            zorder=2,
        )
        ax_series.scatter(
            positive_time,
            comparison.numerical_drawdown_mean[:, radius_index],
            s=18,
            color=color,
            edgecolors="white",
            linewidths=0.4,
            zorder=3,
        )

    ax_series.set_title("Late-time drawdown traces")
    ax_series.set_xlabel("Time [day]")
    ax_series.set_ylabel("Drawdown [m]")
    ax_series.grid(True, which="both", ls=":", alpha=0.4)
    ax_series.legend(loc="best", ncol=min(4, max(1, comparison.monitor_radii_m.size)))
    ax_series.text(
        0.01,
        0.02,
        "Solid lines: analytical   Markers: numerical mean over east/west/north/south",
        transform=ax_series.transAxes,
        fontsize=8.8,
        bbox={"boxstyle": "round,pad=0.24", "fc": "white", "ec": "0.80", "alpha": 0.92},
    )

    residual_vmax = float(np.max(np.abs(comparison.residual_drawdown)))
    if residual_vmax <= 0.0:
        residual_vmax = 1e-9
    image = ax_residual.imshow(
        comparison.residual_drawdown,
        aspect="auto",
        origin="lower",
        extent=[
            float(comparison.monitor_radii_m[0]),
            float(comparison.monitor_radii_m[-1]),
            float(time_days[0]),
            float(time_days[-1]),
        ],
        cmap="coolwarm",
        vmin=-residual_vmax,
        vmax=residual_vmax,
    )
    ax_residual.set_title("Residual heatmap (numerical - analytical)")
    ax_residual.set_xlabel("Radius [m]")
    ax_residual.set_ylabel("Time [day]")
    colorbar = figure.colorbar(image, ax=ax_residual, fraction=0.046, pad=0.04)
    colorbar.set_label("Residual [m]")

    azimuth_abs_deviation = np.abs(
        comparison.numerical_drawdown_by_azimuth - comparison.numerical_drawdown_mean[:, :, None]
    )
    for radius_index, (radius, color) in enumerate(
        zip(comparison.monitor_radii_m, radii_colors, strict=False)
    ):
        ax_azimuth.semilogx(
            positive_time,
            azimuth_abs_deviation[:, radius_index, :].max(axis=1),
            color=color,
            lw=1.8,
            label=f"r={float(radius):.1f} m",
        )
    ax_azimuth.set_title("Azimuthal spread")
    ax_azimuth.set_xlabel("Time [day]")
    ax_azimuth.set_ylabel("Max |drawdown - mean| [m]")
    ax_azimuth.grid(True, which="both", ls=":", alpha=0.4)
    if comparison.monitor_radii_m.size > 0:
        ax_azimuth.legend(loc="best", fontsize=8)

    footer_lines = list(parameter_lines)
    footer_lines.append(
        "space-time RMSE="
        f"{comparison.space_time_rmse:.4f} m   "
        f"space-time max abs={comparison.space_time_max_error:.4f} m   "
        f"final-time RMSE={comparison.final_time_rmse:.4f} m   "
        f"azimuthal spread={comparison.azimuthal_spread:.2e} m"
    )
    max_abs_tol = float(space_time_tol.get("max_abs_error", 0.0))
    if max_abs_tol > 0.0:
        footer_lines.append(f"configured max-abs tolerance={max_abs_tol:.4f} m")

    figure.suptitle(title, fontsize=13)
    figure.text(
        0.5,
        0.01,
        "\n".join(footer_lines),
        ha="center",
        va="bottom",
        fontsize=9,
        family="monospace",
        bbox={"boxstyle": "round,pad=0.32", "fc": "white", "ec": "0.75", "alpha": 0.95},
    )
    figure.subplots_adjust(left=0.08, right=0.96, bottom=0.18, top=0.92, wspace=0.28, hspace=0.35)
    figure.savefig(output_path, bbox_inches="tight")

    if show_plot:
        plt.show(block=True)
    plt.close(figure)
    return output_path
