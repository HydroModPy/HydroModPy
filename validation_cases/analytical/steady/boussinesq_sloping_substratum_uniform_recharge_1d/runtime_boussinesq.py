"""Local ``flow/boussinesq`` runtime for the sloping recharge case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.shared import load_case_metadata
from validation_cases.shared.boussinesq_uniform_strip import (
    run_boussinesq_uniform_strip_case,
)


CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "boussinesq_sloping_substratum_uniform_recharge_1d"
NX = 40
NY = 5
LENGTH_X_M = 400.0
WIDTH_Y_M = 50.0


def _build_linear_profile(
    x_m: float,
    *,
    base_elevation_m: float,
    right_to_left_amplitude_m: float,
) -> float:
    return float(base_elevation_m) + float(right_to_left_amplitude_m) * (
        1.0 - (float(x_m) / LENGTH_X_M)
    )


def _mm_day_to_m_s(recharge_mm_day: float) -> float:
    return float(recharge_mm_day) * 1.0e-3 / 86400.0


def run_boussinesq_sloping_substratum_uniform_recharge_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
) -> object:
    """Run the steady sloping-substratum recharge case locally."""
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
        z_top_m=lambda x_m: _build_linear_profile(
            float(x_m),
            base_elevation_m=float(reference_cfg["topography_base_elevation_m"]),
            right_to_left_amplitude_m=float(reference_cfg["topography_right_to_left_amplitude_m"]),
        ),
        z_bottom_m=lambda x_m: _build_linear_profile(
            float(x_m),
            base_elevation_m=float(reference_cfg["bottom_base_elevation_m"]),
            right_to_left_amplitude_m=float(reference_cfg["bottom_right_to_left_amplitude_m"]),
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
            "active_sinks_sources": ["recharge"],
            "active_bc": ["west_side", "east_side"],
            "sinks_sources": {
                "recharge": {
                    "values": _mm_day_to_m_s(float(reference_cfg["recharge_mm_day"])),
                    "first_clim": "mean",
                }
            },
            "bc": {
                "dirichlet": {
                    "west_side": {"value": float(reference_cfg["west_head"])},
                    "east_side": {"value": float(reference_cfg["east_head"])},
                }
            },
        },
        plan_name="Boussinesq sloping-substratum recharge validation",
        plan_description="Steady 1D strip with a sloping impermeable bottom, uniform recharge, and fixed heads.",
        flow_regime="steady",
    )


__all__ = ["run_boussinesq_sloping_substratum_uniform_recharge_case"]
