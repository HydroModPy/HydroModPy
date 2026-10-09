"""Boussinesq runtime for the thin-aquifer Brutsaert recession case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.analytical.transient.runtime_boussinesq_brutsaert_1d import (
    run_boussinesq_brutsaert_recession_case,
)

from .reference import load_case_parameters

CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "brutsaert_recession_boussinesq_thin_1d"


def run_boussinesq_brutsaert_recession_boussinesq_thin_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    public_solver_label: str = "boussinesq",
):
    """Run the thin-aquifer Brutsaert recession case on one Boussinesq variant."""
    params = load_case_parameters()
    return run_boussinesq_brutsaert_recession_case(
        case_dir=CASE_DIR,
        case_id=CASE_ID,
        caller_file=caller_file,
        timeout=timeout,
        nx=params["nx"],
        ny=params["ny"],
        length_x_m=params["length_x_m"],
        width_y_m=params["width_y_m"],
        z_top_m=params["z_top_m"],
        z_bottom_m=params["z_bottom_m"],
        hydraulic_conductivity_m_s=params["hydraulic_conductivity_m_per_s"],
        storage_coefficient=params["specific_yield"],
        east_head_m=params["east_head_m"],
        steady_recharge_mm_day=params["steady_recharge_mm_day"],
        nper=params["nper"],
        dt_seconds=params["dt_seconds"],
        acceptable_steady_residual_inf=params["acceptable_steady_residual_inf"],
        public_solver_label=public_solver_label,
    )


__all__ = ["run_boussinesq_brutsaert_recession_boussinesq_thin_case"]
