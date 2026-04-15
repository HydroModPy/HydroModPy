"""Local ``flow/boussinesq`` runtime for the periodic-recharge transient case."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from validation_cases.analytical.transient.common import SECONDS_PER_DAY
from validation_cases.analytical.transient.linearized_unconfined_1d import mm_day_to_m_s
from validation_cases.shared import load_case_metadata
from validation_cases.shared.boussinesq_uniform_strip import (
    run_boussinesq_uniform_strip_case,
)


CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "lu_recharge_periodic_1d"
NX = 50
NY = 5
LENGTH_X_M = 100.0
WIDTH_Y_M = 10.0


def _periodic_recharge_series_mm_day(
    *,
    mean_recharge_mm_day: float,
    amplitude_mm_day: float,
    period_days: float,
    phase_radians: float,
    nper: int,
    dt_seconds: float,
) -> list[float]:
    start_days = (np.arange(int(nper), dtype=float) * float(dt_seconds)) / SECONDS_PER_DAY
    angular_frequency = 2.0 * np.pi / float(period_days)
    values = float(mean_recharge_mm_day) + (
        float(amplitude_mm_day) * np.sin((angular_frequency * start_days) + float(phase_radians))
    )
    return [float(value) for value in values]


def run_boussinesq_linearized_unconfined_recharge_periodic_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
) -> object:
    """Run the periodic recharge case through the local transient Boussinesq backend."""
    metadata = load_case_metadata(CASE_DIR)
    reference_cfg = dict(metadata.get("reference", {}))
    output_cfg = dict(metadata.get("output", {}))
    time_cfg = dict(metadata.get("time", {}))

    base_head_m = float(reference_cfg["base_head_m"])
    reference_saturated_thickness_m = float(
        reference_cfg["reference_saturated_thickness_m"]
    )
    nper = int(output_cfg["expected_periods"])
    dt_seconds = float(time_cfg["dt_seconds"])
    recharge_mm_day = _periodic_recharge_series_mm_day(
        mean_recharge_mm_day=float(reference_cfg["mean_recharge_mm_day"]),
        amplitude_mm_day=float(reference_cfg["amplitude_mm_day"]),
        period_days=float(reference_cfg["period_days"]),
        phase_radians=float(reference_cfg.get("phase_radians", 0.0)),
        nper=nper,
        dt_seconds=dt_seconds,
    )
    recharge_m_s = [mm_day_to_m_s(value) for value in recharge_mm_day]

    return run_boussinesq_uniform_strip_case(
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
                    "values": recharge_m_s,
                    "first_clim": "first",
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
        plan_name="Boussinesq periodic-recharge validation",
        plan_description="Transient sinusoidal recharge on a 1D strip",
        flow_regime="transient",
    )


__all__ = ["run_boussinesq_linearized_unconfined_recharge_periodic_case"]
