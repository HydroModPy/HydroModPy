"""Shared comparison and plotting helpers for Brutsaert recession benchmarks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from validation_cases.shared import (
    ValidationRunResult,
    load_case_metadata,
    load_case_tolerances,
    load_time_series_fields,
    max_abs_error,
    max_std_along_axis,
    rmse,
)

from .brutsaert_reference import (
    SECONDS_PER_DAY,
    compute_characteristic_time,
    simulate_baseflow,
)

_SOLVER_DISPLAY_NAMES = {
    "modflownwt": "MODFLOW-NWT",
    "modflow6": "MODFLOW 6",
    "boussinesq": "Boussinesq",
}

_LEGEND_STYLE_MAIN = {
    "loc": "best",
    "fontsize": 8.4,
    "title_fontsize": 8.8,
    "frameon": True,
    "fancybox": True,
    "framealpha": 0.95,
    "borderpad": 0.42,
    "labelspacing": 0.28,
    "handlelength": 1.7,
    "handletextpad": 0.5,
    "markerscale": 0.9,
}

_LEGEND_STYLE_SECONDARY = {
    "loc": "best",
    "fontsize": 7.8,
    "title_fontsize": 8.1,
    "frameon": True,
    "fancybox": True,
    "framealpha": 0.94,
    "borderpad": 0.38,
    "labelspacing": 0.24,
    "handlelength": 1.6,
    "handletextpad": 0.46,
    "markerscale": 0.88,
}

_NWT_BUDGET_HEADER_RE = re.compile(
    r"VOLUMETRIC BUDGET FOR ENTIRE MODEL AT END OF TIME STEP\s+(\d+), STRESS PERIOD\s+(\d+)",
    re.IGNORECASE,
)
_NWT_PERCENT_RE = re.compile(
    r"PERCENT DISCREPANCY =\s*([+-]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class BrutsaertRecessionComparison:
    """Comparison payload for one transient Brutsaert recession validation case."""

    result: ValidationRunResult
    metadata: dict
    tolerances: dict
    solver_display_name: str
    observable_name: str
    period_indices: np.ndarray
    elapsed_seconds: np.ndarray
    elapsed_days: np.ndarray
    numerical_discharge_m3_s: np.ndarray
    analytical_discharge_m3_s: np.ndarray
    residual_discharge_m3_s: np.ndarray
    initial_discharge_m3_s: float
    solution_name: str
    characteristic_time_seconds: float
    characteristic_time_days: float
    row_spread: float
    relative_rmse: float
    relative_max_error: float
    relative_final_error: float
    max_positive_increment_m3_s: float
    solver_budget_max_abs_rate_discrepancy_percent: float | None = None
    solver_budget_last_rate_discrepancy_percent: float | None = None
    solver_budget_first_bad_stress_period: int | None = None

    @property
    def final_elapsed_days(self) -> float:
        return float(self.elapsed_days[-1])


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


def _solver_display_name(solver_name: str | None) -> str:
    normalized = "" if solver_name is None else str(solver_name).strip().lower()
    return _SOLVER_DISPLAY_NAMES.get(normalized, normalized or "Numerical solver")


def _apply_legend_style(ax, *, title: str, secondary: bool = False):
    """Draw one consistently styled legend for Brutsaert validation figures."""
    style = dict(_LEGEND_STYLE_SECONDARY if secondary else _LEGEND_STYLE_MAIN)
    legend = ax.legend(title=title, **style)
    frame = legend.get_frame()
    frame.set_facecolor("white")
    frame.set_edgecolor("#b9c2cf")
    frame.set_linewidth(0.9)
    return legend


def _load_optional_brutsaert_context(postprocess_dir: Path) -> dict | None:
    context_path = postprocess_dir / "brutsaert_context.json"
    if not context_path.exists():
        return None
    with context_path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _load_modflownwt_budget_diagnostics(model_ws: Path) -> dict[str, np.ndarray] | None:
    list_paths = sorted(model_ws.glob("*.list"))
    if not list_paths:
        return None

    stress_periods: list[int] = []
    time_steps: list[int] = []
    rate_percent_discrepancies: list[float] = []
    current_header: tuple[int, int] | None = None

    for raw_line in list_paths[0].read_text(encoding="utf-8", errors="ignore").splitlines():
        header_match = _NWT_BUDGET_HEADER_RE.search(raw_line)
        if header_match is not None:
            current_header = (
                int(header_match.group(1)),
                int(header_match.group(2)),
            )
            continue
        if current_header is None:
            continue
        percent_matches = _NWT_PERCENT_RE.findall(raw_line)
        if not percent_matches:
            continue
        time_step, stress_period = current_header
        stress_periods.append(int(stress_period))
        time_steps.append(int(time_step))
        rate_percent_discrepancies.append(float(percent_matches[-1]))
        current_header = None

    if not rate_percent_discrepancies:
        return None
    return {
        "stress_periods": np.asarray(stress_periods, dtype=int),
        "time_steps": np.asarray(time_steps, dtype=int),
        "rate_percent_discrepancies": np.asarray(rate_percent_discrepancies, dtype=float),
    }


def _load_scalar_series(
    *,
    result: ValidationRunResult,
    observable_name: str,
) -> tuple[np.ndarray, np.ndarray]:
    period_indices, raw_values = load_time_series_fields(
        postprocess_dir=result.postprocess_dir,
        store=result.store,
        sim_id=result.sim_id,
        observable_name=observable_name,
    )
    values = np.asarray(raw_values, dtype=float)
    if values.ndim == 1:
        return np.asarray(period_indices, dtype=int), values
    if values.ndim == 2 and values.shape[1] == 1:
        return np.asarray(period_indices, dtype=int), values[:, 0]
    raise ValueError(
        f"Observable '{observable_name}' must contain one scalar per time step, "
        f"got shape {values.shape}."
    )


def build_brutsaert_recession_comparison(
    *,
    case_dir: Path,
    result: ValidationRunResult,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> BrutsaertRecessionComparison:
    """Load one completed Brutsaert run and compare it to the analytical target."""
    case_metadata = load_case_metadata(case_dir) if metadata is None else metadata
    solver_name = str(getattr(result, "solver_name", "")).strip().lower() or None
    case_tolerances = (
        load_case_tolerances(case_dir, solver=solver_name)
        if tolerances is None
        else tolerances
    )

    output_cfg = dict(case_metadata.get("output", {}))
    time_cfg = dict(case_metadata.get("time", {}))
    reference_cfg = dict(case_metadata.get("reference", {}))
    observable_name = str(output_cfg.get("observable_name", "outlet_discharge_m3_s"))
    _, raw_numerical_discharge = _load_scalar_series(
        result=result,
        observable_name=observable_name,
    )
    warmup_periods_by_solver = output_cfg.get("warmup_periods_by_solver", {})
    warmup_periods = int(output_cfg.get("warmup_periods", 0))
    if isinstance(warmup_periods_by_solver, dict) and solver_name in warmup_periods_by_solver:
        warmup_periods = int(warmup_periods_by_solver[solver_name])
    if warmup_periods < 0:
        raise ValueError("warmup_periods must be >= 0.")
    if warmup_periods >= raw_numerical_discharge.shape[0]:
        raise ValueError(
            f"Warm-up periods ({warmup_periods}) consume the full '{observable_name}' series "
            f"of length {raw_numerical_discharge.shape[0]}."
        )

    context = _load_optional_brutsaert_context(result.postprocess_dir)
    if context is not None and "initial_outlet_discharge_m3_s" in context:
        initial_discharge_m3_s = float(context["initial_outlet_discharge_m3_s"])
    elif warmup_periods > 0:
        initial_discharge_m3_s = float(raw_numerical_discharge[warmup_periods - 1])
    else:
        raise FileNotFoundError(
            "Missing Brutsaert initial-discharge context and no warm-up period is available "
            f"to infer Q0 from '{observable_name}'."
        )

    numerical_discharge_all = np.asarray(
        raw_numerical_discharge[warmup_periods:],
        dtype=float,
    )
    period_indices_all = np.arange(numerical_discharge_all.shape[0], dtype=int)

    expected_periods = int(output_cfg.get("expected_periods", 0))
    if expected_periods > 0:
        assert numerical_discharge_all.shape[0] == expected_periods, (
            f"Unexpected number of periods for {observable_name}: "
            f"{numerical_discharge_all.shape[0]} != {expected_periods}"
        )

    dt_seconds = float(time_cfg["dt_seconds"])
    elapsed_seconds_all = (period_indices_all.astype(float) + 1.0) * dt_seconds
    elapsed_days_all = elapsed_seconds_all / SECONDS_PER_DAY
    compare_start_day = float(reference_cfg.get("compare_start_day", 0.0))
    compare_mask = elapsed_days_all >= compare_start_day
    if not np.any(compare_mask):
        raise ValueError(
            f"No time steps remain after compare_start_day={compare_start_day:.3f} day."
        )

    period_indices = np.asarray(period_indices_all[compare_mask], dtype=int)
    numerical_discharge = np.asarray(
        numerical_discharge_all[compare_mask],
        dtype=float,
    )
    elapsed_seconds = np.asarray(elapsed_seconds_all[compare_mask], dtype=float)
    elapsed_days = np.asarray(elapsed_days_all[compare_mask], dtype=float)

    solution_name = str(reference_cfg["solution"]).strip().lower()
    aquifer_thickness_m = reference_cfg.get("aquifer_thickness_m")
    analytical_discharge_all = simulate_baseflow(
        elapsed_seconds=elapsed_seconds_all,
        initial_discharge_m3_s=initial_discharge_m3_s,
        hydraulic_conductivity_m_per_s=float(
            reference_cfg["hydraulic_conductivity_m_per_s"]
        ),
        specific_yield=float(reference_cfg["specific_yield"]),
        solution=solution_name,
        aquifer_thickness_m=(
            None if aquifer_thickness_m is None else float(aquifer_thickness_m)
        ),
        area_m2=float(reference_cfg["watershed_area_m2"]),
        channel_length_m=float(reference_cfg["channel_length_m"]),
        active_drainage_fraction=float(reference_cfg.get("active_drainage_fraction", 0.7)),
        linearization_constant=float(reference_cfg.get("linearization_constant", 0.346)),
    )
    analytical_discharge = np.asarray(analytical_discharge_all[compare_mask], dtype=float)

    head_observable_name = str(output_cfg.get("head_observable_name", "")).strip()
    row_spread = 0.0
    if head_observable_name:
        _, heads_all = load_time_series_fields(
            postprocess_dir=result.postprocess_dir,
            store=result.store,
            sim_id=result.sim_id,
            observable_name=head_observable_name,
        )
        heads = np.asarray(heads_all, dtype=float)
        heads = heads[warmup_periods:]
        if heads.shape[0] != period_indices_all.shape[0]:
            raise ValueError(
                f"Head observable '{head_observable_name}' does not align with "
                f"'{observable_name}'."
            )
        row_spread = max_std_along_axis(heads[compare_mask], axis=1)

    solver_budget_max_abs_rate_discrepancy_percent = None
    solver_budget_last_rate_discrepancy_percent = None
    solver_budget_first_bad_stress_period = None
    if solver_name == "modflownwt":
        budget_diagnostics = _load_modflownwt_budget_diagnostics(result.model_ws)
        if budget_diagnostics is not None:
            raw_rate_percent = np.asarray(
                budget_diagnostics["rate_percent_discrepancies"],
                dtype=float,
            )
            raw_stress_periods = np.asarray(
                budget_diagnostics["stress_periods"],
                dtype=int,
            )
            if warmup_periods < raw_rate_percent.size:
                compared_rate_percent = raw_rate_percent[warmup_periods:]
                compared_stress_periods = raw_stress_periods[warmup_periods:]
            else:
                compared_rate_percent = raw_rate_percent
                compared_stress_periods = raw_stress_periods
            if compared_rate_percent.size > 0:
                abs_percent = np.abs(compared_rate_percent)
                worst_index = int(np.argmax(abs_percent))
                solver_budget_max_abs_rate_discrepancy_percent = float(abs_percent[worst_index])
                solver_budget_last_rate_discrepancy_percent = float(compared_rate_percent[-1])
                bad_indices = np.flatnonzero(abs_percent > 5.0)
                if bad_indices.size > 0:
                    solver_budget_first_bad_stress_period = int(
                        compared_stress_periods[int(bad_indices[0])]
                    )

    normalization = max(abs(initial_discharge_m3_s), np.finfo(float).eps)
    residual_discharge = np.asarray(
        numerical_discharge - analytical_discharge,
        dtype=float,
    )
    discharge_differences = np.diff(numerical_discharge)
    positive_increments = np.maximum(discharge_differences, 0.0)

    characteristic_time_seconds = compute_characteristic_time(
        initial_discharge_m3_s=initial_discharge_m3_s,
        hydraulic_conductivity_m_per_s=float(
            reference_cfg["hydraulic_conductivity_m_per_s"]
        ),
        specific_yield=float(reference_cfg["specific_yield"]),
        solution=solution_name,
        aquifer_thickness_m=(
            None if aquifer_thickness_m is None else float(aquifer_thickness_m)
        ),
        area_m2=float(reference_cfg["watershed_area_m2"]),
        channel_length_m=float(reference_cfg["channel_length_m"]),
        active_drainage_fraction=float(reference_cfg.get("active_drainage_fraction", 0.7)),
        linearization_constant=float(reference_cfg.get("linearization_constant", 0.346)),
    )

    return BrutsaertRecessionComparison(
        result=result,
        metadata=case_metadata,
        tolerances=case_tolerances,
        solver_display_name=_solver_display_name(getattr(result, "solver_name", None)),
        observable_name=observable_name,
        period_indices=period_indices,
        elapsed_seconds=elapsed_seconds,
        elapsed_days=elapsed_days,
        numerical_discharge_m3_s=numerical_discharge,
        analytical_discharge_m3_s=analytical_discharge,
        residual_discharge_m3_s=residual_discharge,
        initial_discharge_m3_s=initial_discharge_m3_s,
        solution_name=solution_name,
        characteristic_time_seconds=characteristic_time_seconds,
        characteristic_time_days=float(characteristic_time_seconds / SECONDS_PER_DAY),
        row_spread=row_spread,
        relative_rmse=float(rmse(numerical_discharge, analytical_discharge) / normalization),
        relative_max_error=float(
            max_abs_error(numerical_discharge, analytical_discharge) / normalization
        ),
        relative_final_error=float(abs(residual_discharge[-1]) / normalization),
        max_positive_increment_m3_s=(
            float(np.max(positive_increments)) if positive_increments.size else 0.0
        ),
        solver_budget_max_abs_rate_discrepancy_percent=solver_budget_max_abs_rate_discrepancy_percent,
        solver_budget_last_rate_discrepancy_percent=solver_budget_last_rate_discrepancy_percent,
        solver_budget_first_bad_stress_period=solver_budget_first_bad_stress_period,
    )


def plot_brutsaert_recession_comparison(
    comparison: BrutsaertRecessionComparison,
    *,
    output_png: str | Path,
    title: str,
    parameter_lines: tuple[str, ...] | list[str],
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save and optionally display one Brutsaert recession comparison figure."""
    show_plot = _enable_interactive_backend(show_plot)
    output_path = Path(output_png).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    discharge_tol = dict(comparison.tolerances.get("discharge", {}))
    monotonicity_tol = dict(comparison.tolerances.get("monotonicity", {}))
    time_days = np.asarray(comparison.elapsed_days, dtype=float)
    safe_numerical = np.maximum(
        np.asarray(comparison.numerical_discharge_m3_s, dtype=float),
        np.finfo(float).tiny,
    )
    safe_analytical = np.maximum(
        np.asarray(comparison.analytical_discharge_m3_s, dtype=float),
        np.finfo(float).tiny,
    )
    relative_percent = 100.0 * np.divide(
        comparison.residual_discharge_m3_s,
        max(abs(comparison.initial_discharge_m3_s), np.finfo(float).eps),
    )

    figure = plt.figure(figsize=(12.0, 8.2), dpi=dpi)
    grid = figure.add_gridspec(2, 2, height_ratios=(2.1, 1.2), hspace=0.34, wspace=0.28)
    ax_discharge = figure.add_subplot(grid[0, :])
    ax_normalized = figure.add_subplot(grid[1, 0])
    ax_residual = figure.add_subplot(grid[1, 1])

    ax_discharge.semilogy(
        time_days,
        safe_analytical,
        color="#0b4f6c",
        lw=2.2,
        label="Analytical Brutsaert",
        zorder=2,
    )
    ax_discharge.scatter(
        time_days,
        safe_numerical,
        s=28,
        color="#ff7f11",
        edgecolors="white",
        linewidths=0.5,
        label=f"Numerical {comparison.solver_display_name}",
        zorder=3,
    )
    ax_discharge.set_title("Outlet discharge recession")
    ax_discharge.set_xlabel("Time [day]")
    ax_discharge.set_ylabel("Q(t) [m3/s]")
    ax_discharge.grid(True, which="both", ls=":", alpha=0.4)
    _apply_legend_style(ax_discharge, title="Discharge series")
    ax_discharge.text(
        0.01,
        0.03,
        "Line: analytical   Markers: numerical",
        transform=ax_discharge.transAxes,
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.24", "fc": "white", "ec": "0.80", "alpha": 0.92},
    )

    normalization = max(abs(comparison.initial_discharge_m3_s), np.finfo(float).eps)
    ax_normalized.plot(
        time_days,
        comparison.analytical_discharge_m3_s / normalization,
        color="#0b4f6c",
        lw=2.0,
        label="Analytical",
    )
    ax_normalized.scatter(
        time_days,
        comparison.numerical_discharge_m3_s / normalization,
        s=24,
        color="#ff7f11",
        edgecolors="white",
        linewidths=0.5,
        label="Numerical",
    )
    ax_normalized.set_title("Normalized recession")
    ax_normalized.set_xlabel("Time [day]")
    ax_normalized.set_ylabel("Q / Q0 [-]")
    ax_normalized.grid(True, ls=":", alpha=0.4)
    _apply_legend_style(ax_normalized, title="Normalized series", secondary=True)

    ax_residual.axhline(0.0, color="0.45", lw=1.0, ls="--")
    ax_residual.plot(
        time_days,
        relative_percent,
        color="#7a306c",
        lw=1.9,
    )
    ax_residual.scatter(
        time_days,
        relative_percent,
        s=18,
        color="#7a306c",
        edgecolors="white",
        linewidths=0.4,
    )
    ax_residual.set_title("Relative residual")
    ax_residual.set_xlabel("Time [day]")
    ax_residual.set_ylabel("(Qnum - Qref) / Q0 [%]")
    ax_residual.grid(True, ls=":", alpha=0.4)

    footer_lines = list(parameter_lines)
    footer_lines.append(
        "relative RMSE="
        f"{comparison.relative_rmse:.4f}   "
        f"relative max abs={comparison.relative_max_error:.4f}   "
        f"relative final error={comparison.relative_final_error:.4f}   "
        f"row spread={comparison.row_spread:.2e} m"
    )
    rmse_tol = float(discharge_tol.get("relative_rmse", 0.0))
    max_tol = float(discharge_tol.get("relative_max_error", 0.0))
    increase_tol = float(monotonicity_tol.get("max_positive_increment_m3_s", 0.0))
    if rmse_tol > 0.0 or max_tol > 0.0 or increase_tol > 0.0:
        footer_lines.append(
            "configured tolerances: "
            f"rrmse<={rmse_tol:.4f}   "
            f"rmax<={max_tol:.4f}   "
            f"positive increment<={increase_tol:.2e} m3/s"
        )
    if comparison.solver_budget_max_abs_rate_discrepancy_percent is not None:
        budget_line = (
            "MODFLOW-NWT rate budget discrepancy: "
            f"max|%|={comparison.solver_budget_max_abs_rate_discrepancy_percent:.2f}"
        )
        if comparison.solver_budget_first_bad_stress_period is not None:
            budget_line += (
                f"   first bad stress period={comparison.solver_budget_first_bad_stress_period}"
            )
        if comparison.solver_budget_last_rate_discrepancy_percent is not None:
            budget_line += (
                f"   final signed %={comparison.solver_budget_last_rate_discrepancy_percent:.2f}"
            )
        footer_lines.append(budget_line)

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
    figure.subplots_adjust(left=0.08, right=0.96, bottom=0.18, top=0.92, wspace=0.28, hspace=0.34)
    figure.savefig(output_path, bbox_inches="tight")

    if show_plot:
        plt.show(block=True)
    plt.close(figure)
    return output_path


__all__ = [
    "BrutsaertRecessionComparison",
    "build_brutsaert_recession_comparison",
    "plot_brutsaert_recession_comparison",
]
