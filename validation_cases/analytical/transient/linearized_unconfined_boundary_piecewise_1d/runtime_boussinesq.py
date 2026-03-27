"""Local ``flow/boussinesq`` runtime for the boundary-piecewise transient case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.shared import load_case_metadata
from validation_cases.shared.boussinesq_uniform_strip import (
    run_boussinesq_uniform_strip_case,
)


CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "lu_boundary_piecewise_1d"
NX = 50
NY = 5
LENGTH_X_M = 100.0
WIDTH_Y_M = 10.0


def run_boussinesq_linearized_unconfined_boundary_piecewise_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
) -> object:
    """Run the boundary-piecewise case through the local transient Boussinesq backend."""
    metadata = load_case_metadata(CASE_DIR)
    reference_cfg = dict(metadata.get("reference", {}))
    output_cfg = dict(metadata.get("output", {}))
    time_cfg = dict(metadata.get("time", {}))

    base_head_m = float(reference_cfg["base_head_m"])
    reference_saturated_thickness_m = float(
        reference_cfg["reference_saturated_thickness_m"]
    )

    return run_boussinesq_uniform_strip_case(
        case_dir=CASE_DIR,
        case_id=CASE_ID,
        caller_file=caller_file,
        timeout=timeout,
        nx=NX,
        ny=NY,
        nper=int(output_cfg["expected_periods"]),
        dt_seconds=float(time_cfg["dt_seconds"]),
        length_x_m=LENGTH_X_M,
        width_y_m=WIDTH_Y_M,
        z_top_m=base_head_m + reference_saturated_thickness_m,
        z_bottom_m=base_head_m - reference_saturated_thickness_m,
        hydraulic_conductivity_m_s=float(reference_cfg["hydraulic_conductivity_m_per_s"]),
        storage_coefficient=float(reference_cfg["specific_yield"]),
        flow_section={
            "flow_regime": "transient",
            "ic": {"type": "custom", "value": base_head_m},
            "active_sinks_sources": [],
            "active_bc": ["west_side", "east_side"],
            "bc": {
                "dirichlet": {
                    "west_side": {"value": list(reference_cfg["west_head_levels_m"])},
                    "east_side": {"value": base_head_m},
                }
            },
        },
        plan_name="Boussinesq boundary-piecewise validation",
        plan_description="Transient west-boundary piecewise head series on a 1D strip",
        flow_regime="transient",
    )


__all__ = ["run_boussinesq_linearized_unconfined_boundary_piecewise_case"]
