"""Local ``flow/boussinesq`` runtime for the sloping constant-thickness case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.shared import load_case_metadata
from validation_cases.shared.boussinesq_uniform_strip import (
    run_boussinesq_uniform_strip_case,
)

CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "boussinesq_sloping_substratum_constant_thickness_1d"
NX = 40
NY = 5
LENGTH_X_M = 400.0
WIDTH_Y_M = 50.0


def run_boussinesq_sloping_substratum_constant_thickness_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
) -> object:
    """Run the steady sloping-substratum constant-thickness case locally."""
    metadata = load_case_metadata(CASE_DIR)
    reference_cfg = dict(metadata.get("reference", {}))

    return run_boussinesq_uniform_strip_case(
        case_dir=CASE_DIR,
        case_id=CASE_ID,
        caller_file=caller_file,
        timeout=timeout,
        nx=NX,
        ny=NY,
        length_x_m=LENGTH_X_M,
        width_y_m=WIDTH_Y_M,
        z_top_m=lambda x_m: (
            reference_cfg["topography_base_elevation_m"]
            + float(reference_cfg["topography_right_to_left_amplitude_m"])
            * (1.0 - (float(x_m) / LENGTH_X_M))
        ),
        z_bottom_m=lambda x_m: (
            reference_cfg["bottom_base_elevation_m"]
            + float(reference_cfg["bottom_right_to_left_amplitude_m"])
            * (1.0 - (float(x_m) / LENGTH_X_M))
        ),
        hydraulic_conductivity_m_s=float(reference_cfg["hydraulic_conductivity_m_per_s"]),
        storage_coefficient=0.1,
        flow_section={
            "flow_regime": "steady",
            "runtime_backend": "scipy_sparse",
            "ic": {
                "type": "custom",
                "value": 0.5
                * (float(reference_cfg["west_head"]) + float(reference_cfg["east_head"])),
            },
            "active_sinks_sources": [],
            "active_bc": ["west_side", "east_side"],
            "bc": {
                "dirichlet": {
                    "west_side": {"value": float(reference_cfg["west_head"])},
                    "east_side": {"value": float(reference_cfg["east_head"])},
                }
            },
        },
        plan_name="Boussinesq sloping-substratum constant-thickness validation",
        plan_description="Steady 1D strip with a sloping impermeable bottom and constant saturated thickness.",
        flow_regime="steady",
    )


__all__ = ["run_boussinesq_sloping_substratum_constant_thickness_case"]
