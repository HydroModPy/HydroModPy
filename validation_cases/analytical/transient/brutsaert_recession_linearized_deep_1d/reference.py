"""Reference parameters for the deep-aquifer Brutsaert recession case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.shared import load_case_metadata


CASE_DIR = Path(__file__).resolve().parent


def load_case_parameters(metadata: dict | None = None) -> dict:
    """Return one flat mapping of the case parameters used by runtime and plots."""
    case_metadata = load_case_metadata(CASE_DIR) if metadata is None else metadata
    geometry_cfg = dict(case_metadata.get("geometry", {}))
    runtime_cfg = dict(case_metadata.get("runtime", {}))
    time_cfg = dict(case_metadata.get("time", {}))
    reference_cfg = dict(case_metadata.get("reference", {}))
    return {
        "nx": int(geometry_cfg["nx"]),
        "ny": int(geometry_cfg["ny"]),
        "length_x_m": float(geometry_cfg["length_x_m"]),
        "width_y_m": float(geometry_cfg["width_y_m"]),
        "z_top_m": float(geometry_cfg["z_top_m"]),
        "z_bottom_m": float(geometry_cfg["z_bottom_m"]),
        "east_head_m": float(runtime_cfg["east_head_m"]),
        "steady_recharge_mm_day": float(runtime_cfg["steady_recharge_mm_day"]),
        "acceptable_steady_residual_inf": float(
            runtime_cfg.get("acceptable_steady_residual_inf", 1.0e-6)
        ),
        "nper": int(time_cfg["nper"]),
        "dt_seconds": float(time_cfg["dt_seconds"]),
        "solution": str(reference_cfg["solution"]),
        "hydraulic_conductivity_m_per_s": float(reference_cfg["hydraulic_conductivity_m_per_s"]),
        "specific_yield": float(reference_cfg["specific_yield"]),
        "aquifer_thickness_m": float(reference_cfg["aquifer_thickness_m"]),
        "watershed_area_m2": float(reference_cfg["watershed_area_m2"]),
        "channel_length_m": float(reference_cfg["channel_length_m"]),
        "active_drainage_fraction": float(reference_cfg.get("active_drainage_fraction", 0.7)),
        "linearization_constant": float(reference_cfg.get("linearization_constant", 0.346)),
    }


def build_parameter_lines(metadata: dict | None = None) -> tuple[str, ...]:
    """Return short figure footer lines describing the deep Brutsaert setup."""
    params = load_case_parameters(metadata)
    return (
        f"solution={params['solution']}   K={params['hydraulic_conductivity_m_per_s']:.1e} m/s   Sy={params['specific_yield']:.3f}",
        f"b={params['aquifer_thickness_m']:.1f} m   A={params['watershed_area_m2']:.1f} m2   L={params['channel_length_m']:.1f} m",
        f"ag={params['active_drainage_fraction']:.3f}   p={params['linearization_constant']:.3f}   recharge={params['steady_recharge_mm_day']:.2f} mm/day",
        f"strip={params['length_x_m']:.1f} m x {params['width_y_m']:.1f} m   east head={params['east_head_m']:.2f} m   dt={params['dt_seconds'] / 86400.0:.1f} day",
    )


__all__ = ["build_parameter_lines", "load_case_parameters"]
