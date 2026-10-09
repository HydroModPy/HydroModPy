"""Reference parameters for the thin-aquifer Brutsaert recession case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.analytical.transient.brutsaert_common import load_strip_parameters
from validation_cases.shared import load_case_metadata

CASE_DIR = Path(__file__).resolve().parent


def load_case_parameters(metadata: dict | None = None) -> dict:
    """Return one flat mapping of the case parameters used by the PETSc runtime."""
    case_metadata = load_case_metadata(CASE_DIR) if metadata is None else metadata
    strip = load_strip_parameters(CASE_DIR, case_metadata)
    time_cfg = dict(case_metadata.get("time", {}))
    runtime_cfg = dict(case_metadata.get("runtime", {}))
    return {
        "nx": strip.nx,
        "ny": strip.ny,
        "length_x_m": strip.length_x_m,
        "width_y_m": strip.width_y_m,
        "z_top_m": strip.z_top_m,
        "z_bottom_m": strip.z_bottom_m,
        "east_head_m": strip.outlet_head_m,
        "steady_recharge_mm_day": strip.steady_recharge_mm_day,
        "acceptable_steady_residual_inf": float(
            runtime_cfg.get("acceptable_steady_residual_inf", 1.0e-6)
        ),
        "nper": int(time_cfg["nper"]),
        "dt_seconds": float(time_cfg["dt_seconds"]),
        "hydraulic_conductivity_m_per_s": strip.hydraulic_conductivity_m_per_s,
        "specific_yield": strip.specific_yield,
    }


__all__ = ["load_case_parameters"]
