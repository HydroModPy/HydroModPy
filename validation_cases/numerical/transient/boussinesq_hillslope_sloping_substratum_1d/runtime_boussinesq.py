"""Runtime for one transient Boussinesq hillslope case with sloping substratum."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from validation_cases.analytical.steady.boussinesq_piecewise import mm_day_to_m_s
from validation_cases.shared.boussinesq_uniform_strip import run_boussinesq_uniform_strip_case


CASE_ID = "boussinesq_hillslope_sloping_substratum_1d"
CASE_DIR = Path(__file__).resolve().parent
NX = 40
NY = 3
LENGTH_X_M = 400.0
WIDTH_Y_M = 30.0
TOPOGRAPHY_BASE_ELEVATION_M = 5.0
TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M = 5.0
BOTTOM_BASE_ELEVATION_M = -14.0
BOTTOM_RIGHT_TO_LEFT_AMPLITUDE_M = 1.8
HYDRAULIC_CONDUCTIVITY_M_S = 2.0e-5
SPECIFIC_YIELD = 0.10
INITIAL_HEAD_M = 5.25
EAST_HEAD_M = 5.25
DRAINAGE_CONDUCTANCE_M2_S = 1.0e-4
DT_DAYS = 15.0
RECHARGE_SERIES_MM_DAY = (
    0.6,
    0.6,
    1.8,
    1.8,
    3.0,
    3.0,
    4.2,
    4.2,
    5.4,
    5.4,
    7.2,
    7.2,
    6.0,
    6.0,
    4.8,
    4.8,
    3.6,
    3.6,
    2.4,
    2.4,
    1.2,
    1.2,
    0.6,
    0.6,
    0.0,
    0.0,
    0.0,
    0.0,
)


def _linear_profile(
    x_m: np.ndarray,
    *,
    base_elevation_m: float,
    right_to_left_amplitude_m: float,
) -> np.ndarray:
    x = np.asarray(x_m, dtype=float)
    return float(base_elevation_m) + float(right_to_left_amplitude_m) * (1.0 - x / float(LENGTH_X_M))


def build_topography_profile(x_m: np.ndarray) -> np.ndarray:
    return _linear_profile(
        x_m,
        base_elevation_m=TOPOGRAPHY_BASE_ELEVATION_M,
        right_to_left_amplitude_m=TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M,
    )


def build_bottom_profile(x_m: np.ndarray) -> np.ndarray:
    return _linear_profile(
        x_m,
        base_elevation_m=BOTTOM_BASE_ELEVATION_M,
        right_to_left_amplitude_m=BOTTOM_RIGHT_TO_LEFT_AMPLITUDE_M,
    )


def run_boussinesq_hillslope_sloping_substratum_case(
    *,
    caller_file: str | Path = __file__,
    timeout: int = 2400,
):
    recharge_series_m_s = [mm_day_to_m_s(float(value)) for value in RECHARGE_SERIES_MM_DAY]
    return run_boussinesq_uniform_strip_case(
        case_dir=CASE_DIR,
        case_id=CASE_ID,
        caller_file=caller_file,
        timeout=timeout,
        nx=NX,
        ny=NY,
        nper=len(RECHARGE_SERIES_MM_DAY),
        dt_seconds=DT_DAYS * 86_400.0,
        length_x_m=LENGTH_X_M,
        width_y_m=WIDTH_Y_M,
        z_top_m=build_topography_profile,
        z_bottom_m=build_bottom_profile,
        hydraulic_conductivity_m_s=HYDRAULIC_CONDUCTIVITY_M_S,
        storage_coefficient=SPECIFIC_YIELD,
        flow_section={
            "runtime_backend": "local",
            "flow_regime": "transient",
            "runtime_max_iterations": 80,
            "runtime_tol_residual_inf": 1.0e-7,
            "ic": {"type": "custom", "value": INITIAL_HEAD_M},
            "active_sinks_sources": ["recharge"],
            "active_bc": ["east_side", "drainage"],
            "sinks_sources": {
                "recharge": {
                    "values": recharge_series_m_s,
                    "first_clim": "first",
                }
            },
            "bc": {
                "dirichlet": {
                    "east_side": {
                        "type": "dirichlet",
                        "value": EAST_HEAD_M,
                    }
                },
                "cauchy": {
                    "drainage": {
                        "application_domain": "top",
                        "type": "cauchy",
                        "value": DRAINAGE_CONDUCTANCE_M2_S,
                    }
                },
            },
        },
        plan_name="Transient hillslope with sloping substratum",
        plan_description="Transient Boussinesq strip where the surface and substratum slopes are independent.",
        flow_regime="transient",
        export_initial_state=False,
    )


__all__ = [
    "build_bottom_profile",
    "build_topography_profile",
    "run_boussinesq_hillslope_sloping_substratum_case",
]
