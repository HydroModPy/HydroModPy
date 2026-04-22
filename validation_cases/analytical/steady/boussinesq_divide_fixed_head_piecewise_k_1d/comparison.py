"""Comparison workflow for the steady divide piecewise-K validation case."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import flopy.utils.binaryfile as fpu
import numpy as np

from validation_cases.shared import (
    ValidationRunResult,
    load_case_metadata,
    load_case_tolerances,
    load_field,
    max_abs_error,
    max_std_along_axis,
    mean_along_axis,
    rmse,
    run_launcher_validation_case,
)

from .reference import expected_boussinesq_divide_fixed_head_piecewise_profile
from .runtime_boussinesq import run_boussinesq_divide_fixed_head_piecewise_k_case


CASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class BoussinesqDivideFixedHeadPiecewiseKComparison:
    """All arrays and metrics required to validate or plot the case."""

    result: ValidationRunResult
    metadata: dict
    tolerances: dict
    timestep: int
    observable_name: str
    heads: np.ndarray
    x: np.ndarray
    profile_axis: int
    numerical_profile: np.ndarray
    analytical_profile: np.ndarray
    residual_profile: np.ndarray
    rms_error: float
    max_error: float
    row_spread: float


def _compute_watertable_elevation(head: np.ndarray) -> np.ndarray:
    """Collapse one layer stack to a watertable grid without importing solver packages."""
    head_array = np.asarray(head, dtype=float)
    if head_array.ndim < 3:
        return head_array
    if int(head_array.shape[0]) == 1:
        return np.asarray(head_array[0], dtype=float)

    import flopy.utils.postprocessing as pp

    return np.asarray(pp.get_water_table(head_array, -100.0), dtype=float)


def _load_heads_for_comparison(
    *,
    result: ValidationRunResult,
    observable_name: str,
    expected_shape: tuple[int, ...] | None = None,
) -> tuple[int, np.ndarray]:
    """Load heads from the store, postprocess dir, or MODFLOW head file."""
    from validation_cases.shared import load_field

    if result.store is not None and result.sim_id is not None:
        try:
            return load_field(
                store=result.store,
                sim_id=result.sim_id,
                observable_name=observable_name,
                expected_shape=expected_shape,
            )
        except Exception:
            pass

    try:
        from validation_cases.shared import load_last_npy_array

        return load_last_npy_array(result.postprocess_dir, observable_name)
    except FileNotFoundError:
        if observable_name != "watertable_elevation":
            raise

    head_path = result.model_ws / f"{result.model_ws.name}.hds"
    head_fpu = fpu.HeadFile(str(head_path))
    times = head_fpu.get_times()
    assert times, f"No time steps found in {head_path}"

    head = np.asarray(head_fpu.get_data(totim=times[-1]), dtype=float)
    watertable = _compute_watertable_elevation(head)
    return len(times) - 1, np.asarray(watertable, dtype=float)


def build_boussinesq_divide_fixed_head_piecewise_k_comparison(
    *,
    result: ValidationRunResult,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> BoussinesqDivideFixedHeadPiecewiseKComparison:
    """Load one completed run and compare it to the analytical profile."""
    case_metadata = load_case_metadata(CASE_DIR) if metadata is None else metadata
    solver_name = str(getattr(result, "solver_name", "")).strip().lower() or None
    case_tolerances = (
        load_case_tolerances(CASE_DIR, solver=solver_name) if tolerances is None else tolerances
    )

    output_cfg = dict(case_metadata.get("output", {}))
    reference_cfg = dict(case_metadata.get("reference", {}))
    observable_name = str(output_cfg.get("observable_name", "watertable_elevation"))
    expected_shape_by_solver = output_cfg.get("expected_shape_by_solver", {})
    expected_shape = ()
    if isinstance(expected_shape_by_solver, dict) and solver_name in expected_shape_by_solver:
        expected_shape = tuple(expected_shape_by_solver[solver_name])
    else:
        expected_shape = tuple(output_cfg.get("expected_shape", ()))
    timestep, heads = _load_heads_for_comparison(
        result=result,
        observable_name=observable_name,
        expected_shape=expected_shape or None,
    )

    if expected_shape:
        assert tuple(heads.shape) == expected_shape, (
            f"Unexpected shape for {observable_name}: {heads.shape} != {expected_shape}"
        )

    profile_axis = int(reference_cfg.get("profile_axis", 0))
    numerical_profile = mean_along_axis(heads, axis=profile_axis)
    x = np.linspace(
        float(reference_cfg["xmin"]),
        float(reference_cfg["xmax"]),
        numerical_profile.size,
        dtype=float,
    )
    analytical_profile = expected_boussinesq_divide_fixed_head_piecewise_profile(
        xmin=float(reference_cfg["xmin"]),
        xmax=float(reference_cfg["xmax"]),
        ncol=numerical_profile.size,
        east_head=float(reference_cfg["east_head"]),
        recharge_mm_day=float(reference_cfg["recharge_mm_day"]),
        x_zone_breaks_m=reference_cfg["x_zone_breaks_m"],
        hydraulic_conductivity_m_per_s_by_zone=reference_cfg[
            "hydraulic_conductivity_m_per_s_by_zone"
        ],
    )
    residual_profile = np.asarray(numerical_profile - analytical_profile, dtype=float)

    return BoussinesqDivideFixedHeadPiecewiseKComparison(
        result=result,
        metadata=case_metadata,
        tolerances=case_tolerances,
        timestep=timestep,
        observable_name=observable_name,
        heads=np.asarray(heads, dtype=float),
        x=x,
        profile_axis=profile_axis,
        numerical_profile=np.asarray(numerical_profile, dtype=float),
        analytical_profile=np.asarray(analytical_profile, dtype=float),
        residual_profile=residual_profile,
        rms_error=rmse(numerical_profile, analytical_profile),
        max_error=max_abs_error(numerical_profile, analytical_profile),
        row_spread=max_std_along_axis(heads, axis=profile_axis),
    )


def run_boussinesq_divide_fixed_head_piecewise_k_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
) -> BoussinesqDivideFixedHeadPiecewiseKComparison:
    """Run the launcher case and return the full comparison payload."""
    metadata = load_case_metadata(CASE_DIR)
    tolerances = load_case_tolerances(CASE_DIR, solver=solver)
    normalized_solver = None if solver is None else str(solver).strip().lower()
    if normalized_solver == "boussinesq":
        result = run_boussinesq_divide_fixed_head_piecewise_k_case(
            caller_file=caller_file,
            timeout=timeout,
        )
    else:
        result = run_launcher_validation_case(
            case_dir=CASE_DIR,
            test_file=caller_file,
            timeout=timeout,
            solver=solver,
        )
    return build_boussinesq_divide_fixed_head_piecewise_k_comparison(
        result=result,
        metadata=metadata,
        tolerances=tolerances,
    )
