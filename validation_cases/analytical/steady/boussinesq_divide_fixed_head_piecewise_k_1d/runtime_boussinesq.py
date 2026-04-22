"""Launcher-backed `flow/boussinesq` runtime for the divide piecewise-K validation case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.analytical.steady.boussinesq_piecewise import mm_day_to_m_s
from validation_cases.shared.boussinesq_piecewise_strip import (
    run_piecewise_strip_boussinesq_launcher_case,
)
from validation_cases.shared.runtime import ValidationRunResult

CASE_ID = "boussinesq_divide_fixed_head_piecewise_k_1d"
EAST_HEAD_M = 5.0
RECHARGE_MM_DAY = 1.0


def run_boussinesq_divide_fixed_head_piecewise_k_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
) -> ValidationRunResult:
    """Run the divide-fixed-head piecewise-K case through the real launcher."""
    return run_piecewise_strip_boussinesq_launcher_case(
        case_dir=Path(__file__).resolve().parent,
        case_id=CASE_ID,
        caller_file=caller_file,
        timeout=timeout,
        process_id="flow_validation",
        simulation_name="Boussinesq divide validation",
        simulation_description="Steady piecewise-K west-divide strip",
        initial_head_m=7.0,
        east_head_m=EAST_HEAD_M,
        recharge_rate_m_s=mm_day_to_m_s(RECHARGE_MM_DAY),
        runtime_backend="scipy_sparse",
    )


__all__ = ["run_boussinesq_divide_fixed_head_piecewise_k_case"]
