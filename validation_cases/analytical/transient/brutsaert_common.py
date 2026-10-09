"""Shared comparison and plotting helpers for Brutsaert recession benchmarks.

The strip geometry and hydraulics are read from the case configuration, so the
reference cannot drift from the model. ``[reference]`` in ``metadata.toml``
only names the law and the time windows.

Two windows are used:

- ``compare_start_day`` opens the window of the discharge series, its relative
  RMSE and its relative maximum error, both scaled by the initial discharge.
- ``late_window_start_day`` opens the window of the tail metrics: the fitted
  recession coefficient against the analytical one, the fitted exponent ``b`` of
  ``-dQ/dt = a Q^b``, and the RMSE of ``Q / Q_ref - 1``. They weigh the last
  decade of the recession as much as the first.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Mapping
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
    max_std_along_axis,
    rmse,
)
from validation_cases.shared.boussinesq_analytical_runtime import DEFAULT_ENGINE_SOLVER
from validation_cases.shared.boussinesq_plotting import with_boussinesq_method_line
from validation_cases.shared.loaders import resolve_case_mesh_bundle_dir

from .brutsaert_reference import (
    SECONDS_PER_DAY,
    linear_recession_discharge,
    linear_recession_rate,
    nonlinear_recession_coefficient,
    nonlinear_recession_discharge,
)

_SOLVER_DISPLAY_NAMES = {
    "modflow_nwt": "MODFLOW-NWT",
    "modflow6": "MODFLOW 6",
    "modflow6_irregular_tri": "MODFLOW 6 irregular triangles",
    "boussinesq": "Boussinesq",
    DEFAULT_ENGINE_SOLVER: "Boussinesq, default engine",
}

_SOLVER_GRID_SECTIONS = {
    "modflow_nwt": "modflownwt",
    "modflow6": "modflow6",
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

_SOLUTIONS = ("nonlinear", "linear")


@dataclass(frozen=True, slots=True)
class StripParameters:
    """Strip geometry and hydraulics read from one case configuration."""

    length_x_m: float
    width_y_m: float
    nx: int
    ny: int
    z_top_m: float
    z_bottom_m: float
    hydraulic_conductivity_m_per_s: float
    specific_yield: float
    outlet_head_m: float
    steady_recharge_mm_day: float

    @property
    def outlet_saturated_thickness_m(self) -> float:
        """Saturated thickness at the fixed-head outlet, in m."""
        return self.outlet_head_m - self.z_bottom_m

    @property
    def steady_recharge_m_per_s(self) -> float:
        """Warm-up recharge rate, in m/s."""
        return self.steady_recharge_mm_day / 1000.0 / SECONDS_PER_DAY


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
    drainage_length_m: float
    outlet_width_m: float
    recession_coefficient: float
    characteristic_time_seconds: float
    characteristic_time_days: float
    late_window_start_day: float
    recession_coefficient_relative_error: float
    recession_exponent: float
    late_relative_rmse: float
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

    @property
    def expected_recession_exponent(self) -> float:
        """Exponent ``b`` of ``-dQ/dt = a Q^b`` the analytical law predicts."""
        return 1.5 if self.solution_name == "nonlinear" else 1.0


def _quantity(raw: object, unit: str, *, label: str) -> float:
    """Return one config value written as a number or as ``"<number> <unit>"``."""
    if isinstance(raw, int | float):
        return float(raw)
    parts = str(raw).split()
    if len(parts) == 2 and parts[1] == unit:
        return float(parts[0])
    raise ValueError(f"{label} must be a number or '<number> {unit}', got {raw!r}.")


def load_strip_parameters(case_dir: Path, metadata: Mapping | None = None) -> StripParameters:
    """Read the strip geometry and hydraulics from the case base configuration."""
    case_metadata = load_case_metadata(case_dir) if metadata is None else metadata
    config = load_case_config(case_dir, str(case_metadata["base_config"]))
    synthetic = config["geographic"]["synthetic"]
    grid = synthetic["grid"]
    depth_model = config["domain"]["depth_model"]
    if depth_model.get("kind") != "constant_thickness":
        raise ValueError(
            "A Brutsaert strip needs [domain.depth_model] kind = 'constant_thickness'."
        )
    z_top_m = _quantity(
        synthetic["topography"]["base_elevation"], "m", label="topography.base_elevation"
    )
    thickness_m = _quantity(depth_model["thickness"], "m", label="depth_model.thickness")
    params = config["flow"]["param"]
    outlet = config["flow"]["bc"]["east_side"]["forcing"]
    if str(outlet.get("units", "m")) != "m":
        raise ValueError("flow.bc.east_side.forcing must be given in m.")
    recharge_sources = config["data"]["recharge"]["sources"]
    return StripParameters(
        length_x_m=_quantity(grid["length_x"], "m", label="grid.length_x"),
        width_y_m=_quantity(grid["length_y"], "m", label="grid.length_y"),
        nx=int(grid["nx"]),
        ny=int(grid["ny"]),
        z_top_m=z_top_m,
        z_bottom_m=z_top_m - thickness_m,
        hydraulic_conductivity_m_per_s=_quantity(
            params["K"]["field"]["value"], "m/s", label="flow.param.K"
        ),
        specific_yield=_quantity(params["Sy"]["field"]["value"], "-", label="flow.param.Sy"),
        outlet_head_m=float(outlet["value"]),
        steady_recharge_mm_day=float(recharge_sources[0]["values"][0]),
    )


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def bundle_outlet_offset_m(bundle_dir: Path, length_x_m: float) -> float:
    """Return the mean distance from the east edge to the centres of its boundary cells.

    A mesh solver pins the outlet head at the centroid of each cell that owns
    an east boundary edge. The mean is weighted by edge length, the width each
    cell drains.
    """
    nodes_x = {row["node_id"]: float(row["x"]) for row in _read_csv_rows(bundle_dir / "nodes.csv")}
    centroid_x = {
        row["cell_id"]: float(row["centroid_x"]) for row in _read_csv_rows(bundle_dir / "cells.csv")
    }
    tolerance_m = 1.0e-6 * max(abs(float(length_x_m)), 1.0)
    weighted_offset = 0.0
    total_length = 0.0
    for edge in _read_csv_rows(bundle_dir / "edges.csv"):
        if edge["cell_b"].strip() != "":
            continue
        if not all(
            abs(nodes_x[edge[key]] - float(length_x_m)) <= tolerance_m
            for key in ("node_a", "node_b")
        ):
            continue
        edge_length = float(edge["length_m"])
        weighted_offset += edge_length * (float(length_x_m) - centroid_x[edge["cell_a"]])
        total_length += edge_length
    if total_length <= 0.0:
        raise ValueError(f"No east boundary edge found in mesh bundle {bundle_dir}.")
    return weighted_offset / total_length


def outlet_offset_m(
    *,
    case_dir: Path,
    metadata: Mapping,
    params: StripParameters,
    solver_name: str | None,
    result: ValidationRunResult | None = None,
) -> float:
    """Return the distance from the east edge to the cells that hold the outlet head.

    Every backend pins the head at cell centres, not on the edge. A structured
    MODFLOW grid holds it half a column inside; a mesh, at the centroids of the
    triangles along the edge.
    """
    normalized = str(solver_name or "").strip().lower()
    bundle_dir = resolve_case_mesh_bundle_dir(case_dir, metadata, normalized)
    strip_runtime = normalized in {"boussinesq", DEFAULT_ENGINE_SOLVER}
    if bundle_dir is None and strip_runtime and result is not None:
        candidate = Path(result.out_path) / "mesh_bundle"
        bundle_dir = candidate if (candidate / "edges.csv").exists() else None
    if bundle_dir is not None:
        return bundle_outlet_offset_m(bundle_dir, params.length_x_m)
    nx = params.nx
    section = _SOLVER_GRID_SECTIONS.get(normalized)
    config_files = metadata.get("config_files", {})
    if section is not None and isinstance(config_files, Mapping) and normalized in config_files:
        solver_config = load_case_config(case_dir, str(config_files[normalized]))
        planar = solver_config.get(section, {}).get("sgrid", {}).get("planar", {})
        nx = int(planar.get("nx", nx))
    return 0.5 * params.length_x_m / float(nx)


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


def _period_end_rows(values: np.ndarray, n_periods: int, *, label: str) -> np.ndarray:
    """Keep the last time step of each stress period.

    MODFLOW 6 stores one output per stress period, MODFLOW-NWT one per time
    step. Every period of these cases has the same number of steps.
    """
    n_rows = int(values.shape[0])
    if n_rows == n_periods:
        return values
    if n_periods <= 0 or n_rows % n_periods != 0:
        raise ValueError(
            f"'{label}' has {n_rows} outputs, which is not a whole number of "
            f"steps per period for {n_periods} stress periods."
        )
    steps = n_rows // n_periods
    return values[steps - 1 :: steps]


def _load_scalar_series(
    *,
    result: ValidationRunResult,
    observable_name: str,
) -> np.ndarray:
    _, raw_values = load_time_series_fields(
        store=result.store,
        sim_id=result.sim_id,
        observable_name=observable_name,
    )
    values = np.asarray(raw_values, dtype=float)
    if values.ndim == 1:
        return values
    if values.ndim == 2 and values.shape[1] == 1:
        return values[:, 0]
    raise ValueError(
        f"Observable '{observable_name}' must contain one scalar per time step, "
        f"got shape {values.shape}."
    )


def _fit_recession_exponent(elapsed_seconds: np.ndarray, discharge: np.ndarray) -> float:
    """Fit ``b`` of ``-dQ/dt = a Q^b`` on successive outputs.

    Each interval gives ``-dQ/dt`` as a secant slope, set against the geometric
    mean of its two discharges. On an exact power law this estimator is
    unbiased to 1e-4 at the output spacing of these cases.
    """
    t = np.asarray(elapsed_seconds, dtype=float)
    q = np.asarray(discharge, dtype=float)
    decline = -np.diff(q) / np.diff(t)
    mean_q = np.sqrt(q[1:] * q[:-1])
    valid = (decline > 0.0) & (mean_q > 0.0)
    if int(np.count_nonzero(valid)) < 3:
        return float("nan")
    return float(np.polyfit(np.log(mean_q[valid]), np.log(decline[valid]), 1)[0])


def _load_budget_fields(
    *, solver_name: str | None, result: ValidationRunResult, warmup_periods: int
) -> tuple[float | None, float | None, int | None]:
    if solver_name != "modflow_nwt":
        return None, None, None
    budget = _load_modflownwt_budget_diagnostics(result.model_ws)
    if budget is None:
        return None, None, None
    rate_percent = np.asarray(budget["rate_percent_discrepancies"], dtype=float)
    stress_periods = np.asarray(budget["stress_periods"], dtype=int)
    compared = stress_periods > warmup_periods
    if not np.any(compared):
        compared = np.ones_like(stress_periods, dtype=bool)
    rate_percent = rate_percent[compared]
    stress_periods = stress_periods[compared]
    abs_percent = np.abs(rate_percent)
    worst = int(np.argmax(abs_percent))
    bad = np.flatnonzero(abs_percent > 5.0)
    return (
        float(abs_percent[worst]),
        float(rate_percent[-1]),
        int(stress_periods[int(bad[0])]) if bad.size > 0 else None,
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
        load_case_tolerances(case_dir, solver=solver_name) if tolerances is None else tolerances
    )
    params = load_strip_parameters(case_dir, case_metadata)

    output_cfg = dict(case_metadata.get("output", {}))
    time_cfg = dict(case_metadata.get("time", {}))
    reference_cfg = dict(case_metadata.get("reference", {}))
    solution_name = str(reference_cfg["solution"]).strip().lower()
    if solution_name not in _SOLUTIONS:
        raise ValueError(f"Unsupported Brutsaert solution '{solution_name}'.")
    observable_name = str(output_cfg.get("observable_name", "outlet_discharge_m3_s"))

    warmup_periods_by_solver = output_cfg.get("warmup_periods_by_solver", {})
    warmup_periods = int(output_cfg.get("warmup_periods", 0))
    if isinstance(warmup_periods_by_solver, dict) and solver_name in warmup_periods_by_solver:
        warmup_periods = int(warmup_periods_by_solver[solver_name])
    if warmup_periods < 0:
        raise ValueError("warmup_periods must be >= 0.")
    expected_periods = int(output_cfg["expected_periods"])
    n_periods = warmup_periods + expected_periods

    raw_numerical_discharge = _period_end_rows(
        _load_scalar_series(result=result, observable_name=observable_name),
        n_periods,
        label=observable_name,
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

    numerical_discharge_all = np.asarray(raw_numerical_discharge[warmup_periods:], dtype=float)
    period_indices_all = np.arange(numerical_discharge_all.shape[0], dtype=int)
    dt_seconds = float(time_cfg["dt_seconds"])
    elapsed_seconds_all = (period_indices_all.astype(float) + 1.0) * dt_seconds
    elapsed_days_all = elapsed_seconds_all / SECONDS_PER_DAY

    compare_start_day = float(reference_cfg.get("compare_start_day", 0.0))
    late_start_day = float(reference_cfg["late_window_start_day"])
    compare_mask = elapsed_days_all >= compare_start_day - 1.0e-9
    late_mask = elapsed_days_all >= late_start_day - 1.0e-9
    if int(np.count_nonzero(late_mask)) < 4:
        raise ValueError(f"The late window from day {late_start_day:g} holds fewer than 4 outputs.")
    if not np.any(compare_mask):
        raise ValueError(f"No output remains after compare_start_day={compare_start_day:g} day.")

    outlet_offset = outlet_offset_m(
        case_dir=case_dir,
        metadata=case_metadata,
        params=params,
        solver_name=solver_name,
        result=result,
    )
    drainage_length_m = params.length_x_m - outlet_offset
    outlet_width_m = params.width_y_m
    late_t = elapsed_seconds_all[late_mask]
    late_q = numerical_discharge_all[late_mask]

    if solution_name == "nonlinear":
        coefficient = nonlinear_recession_coefficient(
            hydraulic_conductivity_m_per_s=params.hydraulic_conductivity_m_per_s,
            specific_yield=params.specific_yield,
            drainage_length_m=drainage_length_m,
            outlet_width_m=outlet_width_m,
        )
        inverse_root = late_q**-0.5
        virtual_origin = float(np.mean(inverse_root - 0.5 * coefficient * late_t))
        analytical_discharge_all = nonlinear_recession_discharge(
            elapsed_seconds=elapsed_seconds_all,
            recession_coefficient=coefficient,
            virtual_origin=virtual_origin,
        )
        fitted_slope = float(np.polyfit(late_t, inverse_root, 1)[0])
        coefficient_relative_error = 2.0 * fitted_slope / coefficient - 1.0
        characteristic_time_seconds = 1.0 / (0.5 * coefficient * np.sqrt(initial_discharge_m3_s))
    else:
        coefficient = linear_recession_rate(
            hydraulic_conductivity_m_per_s=params.hydraulic_conductivity_m_per_s,
            specific_yield=params.specific_yield,
            saturated_thickness_m=params.outlet_saturated_thickness_m,
            drainage_length_m=drainage_length_m,
        )
        # The steady discharge is the recharge that reaches the aquifer, which
        # tells how much of the strip the model recharges.
        recharged_length_m = min(
            initial_discharge_m3_s / (params.steady_recharge_m_per_s * outlet_width_m),
            drainage_length_m,
        )
        analytical_discharge_all = linear_recession_discharge(
            elapsed_seconds=elapsed_seconds_all,
            initial_discharge_m3_s=initial_discharge_m3_s,
            recession_rate_per_s=coefficient,
            drainage_length_m=drainage_length_m,
            recharged_length_m=recharged_length_m,
        )
        fitted_slope = float(np.polyfit(late_t, np.log(late_q), 1)[0])
        coefficient_relative_error = -fitted_slope / coefficient - 1.0
        characteristic_time_seconds = 1.0 / coefficient

    late_ratio = late_q / analytical_discharge_all[late_mask] - 1.0
    late_relative_rmse = float(np.sqrt(np.mean(late_ratio**2)))
    recession_exponent = _fit_recession_exponent(late_t, late_q)

    period_indices = np.asarray(period_indices_all[compare_mask], dtype=int)
    numerical_discharge = np.asarray(numerical_discharge_all[compare_mask], dtype=float)
    analytical_discharge = np.asarray(analytical_discharge_all[compare_mask], dtype=float)
    elapsed_seconds = np.asarray(elapsed_seconds_all[compare_mask], dtype=float)
    elapsed_days = np.asarray(elapsed_days_all[compare_mask], dtype=float)

    head_observable_name = str(output_cfg.get("head_observable_name", "")).strip()
    row_spread = 0.0
    if head_observable_name:
        expected_head_shape = None
        expected_shape_by_solver = output_cfg.get("expected_spatial_shape_by_solver", {})
        if isinstance(expected_shape_by_solver, dict) and solver_name in expected_shape_by_solver:
            expected_head_shape = tuple(expected_shape_by_solver[solver_name])
        elif solver_name == "modflow6_irregular_tri":
            expected_head_shape = (params.ny, params.nx)
        _, heads_all = load_time_series_fields(
            store=result.store,
            sim_id=result.sim_id,
            observable_name=head_observable_name,
            expected_spatial_shape=expected_head_shape,
        )
        heads = _period_end_rows(
            np.asarray(heads_all, dtype=float), n_periods, label=head_observable_name
        )[warmup_periods:]
        if heads.shape[0] != period_indices_all.shape[0]:
            raise ValueError(
                f"Head observable '{head_observable_name}' does not align with '{observable_name}'."
            )
        row_spread = max_std_along_axis(heads[compare_mask], axis=1)

    budget_max, budget_last, budget_first_bad = _load_budget_fields(
        solver_name=solver_name, result=result, warmup_periods=warmup_periods
    )

    normalization = max(abs(initial_discharge_m3_s), np.finfo(float).eps)
    residual_discharge = np.asarray(numerical_discharge - analytical_discharge, dtype=float)
    positive_increments = np.maximum(np.diff(numerical_discharge_all), 0.0)

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
        drainage_length_m=float(drainage_length_m),
        outlet_width_m=float(outlet_width_m),
        recession_coefficient=float(coefficient),
        characteristic_time_seconds=float(characteristic_time_seconds),
        characteristic_time_days=float(characteristic_time_seconds / SECONDS_PER_DAY),
        late_window_start_day=late_start_day,
        recession_coefficient_relative_error=float(coefficient_relative_error),
        recession_exponent=recession_exponent,
        late_relative_rmse=late_relative_rmse,
        row_spread=row_spread,
        relative_rmse=float(rmse(numerical_discharge, analytical_discharge) / normalization),
        relative_max_error=float(
            max_abs_error(numerical_discharge, analytical_discharge) / normalization
        ),
        relative_final_error=float(abs(residual_discharge[-1]) / normalization),
        max_positive_increment_m3_s=(
            float(np.max(positive_increments)) if positive_increments.size else 0.0
        ),
        solver_budget_max_abs_rate_discrepancy_percent=budget_max,
        solver_budget_last_rate_discrepancy_percent=budget_last,
        solver_budget_first_bad_stress_period=budget_first_bad,
    )


def build_parameter_lines(
    comparison: BrutsaertRecessionComparison,
) -> tuple[str, ...]:
    """Return short figure footer lines describing one Brutsaert setup."""
    params = load_strip_parameters(comparison.result.case_dir, comparison.metadata)
    law = (
        "nonlinear: -dQ/dt = a Q^1.5"
        if comparison.solution_name == "nonlinear"
        else "linear: Q = sum of modes, -dQ/dt = a Q late"
    )
    return (
        f"{law}   a={comparison.recession_coefficient:.4e}   "
        f"K={params.hydraulic_conductivity_m_per_s:.1e} m/s   Sy={params.specific_yield:.3f}",
        f"strip={params.length_x_m:.1f} m x {params.width_y_m:.1f} m   "
        f"drainage length B={comparison.drainage_length_m:.3f} m   "
        f"outlet saturated thickness={params.outlet_saturated_thickness_m:.2f} m",
        f"warm-up recharge={params.steady_recharge_mm_day:.2f} mm/day   "
        f"late window from day {comparison.late_window_start_day:g}",
    )


def plot_brutsaert_recession_comparison(
    comparison: BrutsaertRecessionComparison,
    *,
    output_png: str | Path,
    title: str,
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save and optionally display one Brutsaert recession comparison figure."""
    show_plot = _enable_interactive_backend(show_plot)
    output_path = Path(output_png).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    recession_tol = dict(comparison.tolerances.get("recession", {}))
    time_days = np.asarray(comparison.elapsed_days, dtype=float)
    safe_numerical = np.maximum(
        np.asarray(comparison.numerical_discharge_m3_s, dtype=float),
        np.finfo(float).tiny,
    )
    safe_analytical = np.maximum(
        np.asarray(comparison.analytical_discharge_m3_s, dtype=float),
        np.finfo(float).tiny,
    )
    relative_percent = 100.0 * (safe_numerical / safe_analytical - 1.0)

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
        label="Analytical",
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
    ax_discharge.axvline(comparison.late_window_start_day, color="0.55", lw=1.0, ls=":")
    ax_discharge.set_title("Outlet discharge recession")
    ax_discharge.set_xlabel("Time [day]")
    ax_discharge.set_ylabel("Q(t) [m3/s]")
    ax_discharge.grid(True, which="both", ls=":", alpha=0.4)
    _apply_legend_style(ax_discharge, title="Discharge series")

    if comparison.solution_name == "nonlinear":
        transform_label = "Q^(-1/2) [(m3/s)^(-1/2)]"
        numerical_transform = safe_numerical**-0.5
        analytical_transform = safe_analytical**-0.5
    else:
        transform_label = "ln Q [-]"
        numerical_transform = np.log(safe_numerical)
        analytical_transform = np.log(safe_analytical)
    ax_normalized.plot(time_days, analytical_transform, color="#0b4f6c", lw=2.0, label="Analytical")
    ax_normalized.scatter(
        time_days,
        numerical_transform,
        s=24,
        color="#ff7f11",
        edgecolors="white",
        linewidths=0.5,
        label="Numerical",
    )
    ax_normalized.set_title("Recession on its linear axis")
    ax_normalized.set_xlabel("Time [day]")
    ax_normalized.set_ylabel(transform_label)
    ax_normalized.grid(True, ls=":", alpha=0.4)
    _apply_legend_style(ax_normalized, title="Linearized series", secondary=True)

    ax_residual.axhline(0.0, color="0.45", lw=1.0, ls="--")
    ax_residual.plot(time_days, relative_percent, color="#7a306c", lw=1.9)
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
    ax_residual.set_ylabel("Qnum / Qref - 1 [%]")
    ax_residual.grid(True, ls=":", alpha=0.4)

    footer_lines = list(build_parameter_lines(comparison))
    footer_lines.append(
        "coefficient error="
        f"{comparison.recession_coefficient_relative_error:+.4f}   "
        f"exponent b={comparison.recession_exponent:.4f} "
        f"(law {comparison.expected_recession_exponent:g})   "
        f"late relative RMSE={comparison.late_relative_rmse:.4f}   "
        f"row spread={comparison.row_spread:.2e} m"
    )
    if recession_tol:
        footer_lines.append(
            "tolerances: "
            + "   ".join(f"{key}<={float(value):.3g}" for key, value in recession_tol.items())
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
        footer_lines.append(budget_line)
    footer_lines = with_boussinesq_method_line(comparison.result, footer_lines)

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
    figure.subplots_adjust(left=0.08, right=0.96, bottom=0.2, top=0.92, wspace=0.28, hspace=0.34)
    figure.savefig(output_path, bbox_inches="tight")

    if show_plot:
        plt.show(block=True)
    plt.close(figure)
    return output_path


__all__ = [
    "BrutsaertRecessionComparison",
    "StripParameters",
    "build_brutsaert_recession_comparison",
    "build_parameter_lines",
    "bundle_outlet_offset_m",
    "load_strip_parameters",
    "outlet_offset_m",
    "plot_brutsaert_recession_comparison",
]
