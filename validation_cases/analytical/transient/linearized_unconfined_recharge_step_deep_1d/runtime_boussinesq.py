"""Local ``flow/boussinesq`` runtime for the deep-aquifer recharge-step case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.analytical.transient.linearized_unconfined_1d import mm_day_to_m_s
from validation_cases.analytical.transient.runtime_boussinesq_1d import (
    run_boussinesq_transient_uniform_strip_case,
)
from validation_cases.shared import load_case_metadata


CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "lu_recharge_step_deep_1d"
NX = 40
NY = 3
LENGTH_X_M = 100.0
WIDTH_Y_M = 10.0


def run_boussinesq_linearized_unconfined_recharge_step_deep_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
) -> object:
    """Run the deep recharge-step case through the local transient Boussinesq backend."""
    metadata = load_case_metadata(CASE_DIR)
    reference_cfg = dict(metadata.get("reference", {}))
    output_cfg = dict(metadata.get("output", {}))
    time_cfg = dict(metadata.get("time", {}))

    base_head_m = float(reference_cfg["base_head_m"])
    reference_saturated_thickness_m = float(reference_cfg["reference_saturated_thickness_m"])
    recharge_rate_m_s = mm_day_to_m_s(float(reference_cfg["recharge_mm_day"]))
    nper = int(output_cfg["expected_periods"])
    dt_seconds = float(time_cfg["dt_seconds"])

    return run_boussinesq_transient_uniform_strip_case(
        case_dir=CASE_DIR,
        case_id=CASE_ID,
        caller_file=caller_file,
        timeout=timeout,
        nx=NX,
        ny=NY,
        nper=nper,
        dt_seconds=dt_seconds,
        length_x_m=LENGTH_X_M,
        width_y_m=WIDTH_Y_M,
        z_top_m=base_head_m + reference_saturated_thickness_m,
        z_bottom_m=base_head_m - reference_saturated_thickness_m,
        hydraulic_conductivity_m_s=float(reference_cfg["hydraulic_conductivity_m_per_s"]),
        storage_coefficient=float(reference_cfg["specific_yield"]),
        flow_section={
            "flow_regime": "transient",
            "ic": {"type": "custom", "value": base_head_m},
            "active_sinks_sources": ["recharge"],
            "active_bc": ["west_side", "east_side"],
            "sinks_sources": {
                "recharge": {
                    "values": recharge_rate_m_s,
                    "first_clim": "mean",
                    "units": "m/s",
                }
            },
            "bc": {
                "dirichlet": {
                    "west_side": {"value": base_head_m},
                    "east_side": {"value": base_head_m},
                }
            },
        },
        plan_name="Boussinesq recharge-step deep validation",
        plan_description="Transient uniform recharge step on a deeper 1D strip",
    )


__all__ = ["run_boussinesq_linearized_unconfined_recharge_step_deep_case"]
