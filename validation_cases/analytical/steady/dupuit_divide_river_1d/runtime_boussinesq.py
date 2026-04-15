"""Local ``flow/boussinesq`` runtime for the steady Dupuit divide-river case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.analytical.steady.boussinesq_piecewise import mm_day_to_m_s
from validation_cases.shared import load_case_metadata
from validation_cases.shared.boussinesq_uniform_strip import (
    run_boussinesq_uniform_strip_case,
)


CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "dupuit_divide_river_1d"
NX = 40
NY = 5
LENGTH_X_M = 400.0
WIDTH_Y_M = 50.0


def run_boussinesq_dupuit_divide_river_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
) -> object:
    """Run the steady Dupuit divide-river case through the local Boussinesq backend."""
    metadata = load_case_metadata(CASE_DIR)
    reference_cfg = dict(metadata.get("reference", {}))
    aquifer_thickness_m = float(reference_cfg["aquifer_thickness_m"])
    river_head_m = float(reference_cfg["river_head"])

    return run_boussinesq_uniform_strip_case(
        case_dir=CASE_DIR,
        case_id=CASE_ID,
        caller_file=caller_file,
        timeout=timeout,
        nx=NX,
        ny=NY,
        length_x_m=LENGTH_X_M,
        width_y_m=WIDTH_Y_M,
        z_top_m=aquifer_thickness_m,
        z_bottom_m=0.0,
        hydraulic_conductivity_m_s=float(reference_cfg["hydraulic_conductivity_m_per_s"]),
        storage_coefficient=0.1,
        flow_section={
            "flow_regime": "steady",
            "ic": {"type": "custom", "value": river_head_m + 4.0},
            "active_sinks_sources": ["recharge"],
            "active_bc": ["east_side"],
            "sinks_sources": {
                "recharge": {
                    "values": mm_day_to_m_s(float(reference_cfg["recharge_mm_day"])),
                    "first_clim": "mean",
                    "units": "m/s",
                }
            },
            "bc": {
                "dirichlet": {
                    "east_side": {"value": river_head_m},
                }
            },
        },
        plan_name="Boussinesq Dupuit divide-river validation",
        plan_description="Steady 1D strip with west divide, east fixed head, and recharge",
        flow_regime="steady",
    )


__all__ = ["run_boussinesq_dupuit_divide_river_case"]
