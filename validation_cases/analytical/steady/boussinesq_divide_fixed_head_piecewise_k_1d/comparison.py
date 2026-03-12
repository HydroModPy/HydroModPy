"""Comparison workflow for the steady divide piecewise-K validation case."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import flopy.utils.binaryfile as fpu
import numpy as np

from hydromodpy.solver.modflow_nwt.modflow.postprocess import compute_watertable_elevation
from validation_cases.shared import (
    ValidationRunResult,
    load_case_metadata,
    load_case_tolerances,
    load_last_npy_array,
    max_abs_error,
    max_std_along_axis,
    mean_along_axis,
    rmse,
    run_launcher_validation_case,
)

from .reference import expected_boussinesq_divide_fixed_head_piecewise_profile


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


def _load_heads_for_comparison(
    *,
    result: ValidationRunResult,
    observable_name: str,
) -> tuple[int, np.ndarray]:
    """Load postprocessed heads, or fall back to the last MODFLOW head file."""
    try:
        return load_last_npy_array(result.postprocess_dir, observable_name)
    except FileNotFoundError:
        if observable_name != "watertable_elevation":
            raise

    head_path = result.model_ws / f"{result.model_ws.name}.hds"
    head_fpu = fpu.HeadFile(str(head_path))
    times = head_fpu.get_times()
    assert times, f"No time steps found in {head_path}"

    head = np.asarray(head_fpu.get_data(totim=times[-1]), dtype=float)
    watertable = compute_watertable_elevation(head, head.shape[0])
    return len(times) - 1, np.asarray(watertable, dtype=float)


def build_boussinesq_divide_fixed_head_piecewise_k_comparison(
    *,
    result: ValidationRunResult,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> BoussinesqDivideFixedHeadPiecewiseKComparison:
    """Load one completed run and compare it to the analytical profile."""
    case_metadata = load_case_metadata(CASE_DIR) if metadata is None else metadata
    case_tolerances = load_case_tolerances(CASE_DIR, solver=solver) if tolerances is None else tolerances

    output_cfg = dict(case_metadata.get("output", {}))
    reference_cfg = dict(case_metadata.get("reference", {}))
    observable_name = str(output_cfg.get("observable_name", "watertable_elevation"))
    timestep, heads = _load_heads_for_comparison(
        result=result,
        observable_name=observable_name,
    )

    expected_shape = tuple(output_cfg.get("expected_shape", ()))
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
        hydraulic_conductivity_m_per_s_by_zone=reference_cfg["hydraulic_conductivity_m_per_s_by_zone"],
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



