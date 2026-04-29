"""Variable aliases, native units, and unit conversions for comparisons."""

from __future__ import annotations

import math
from typing import Any


def _variable_candidates(variable: str) -> tuple[str, ...]:
    """Return postprocess file aliases for one observable variable."""
    key = variable.strip()
    lowered = key.lower()
    candidates = [key]
    alias_map = {
        "outlet_flux": [
            "outlet_discharge_east_side_m3_s",
            "drainage_flux_history_m3_s",
            "drainage_flux_m3_s",
            "accumulation_flux",
        ],
        "outlet_flux_m3_s": [
            "outlet_discharge_east_side_m3_s",
            "drainage_flux_history_m3_s",
            "drainage_flux_m3_s",
            "accumulation_flux",
        ],
        "accumulation_flux": [
            "accumulation_flux",
            "drainage_flux_history_m3_s",
            "drainage_flux_m3_s",
        ],
        "outlet_discharge": ["outlet_discharge_east_side_m3_s"],
        "outlet_accumulation": [
            "accumulation_flux",
            "drainage_flux_history_m3_s",
            "drainage_flux_m3_s",
        ],
        "accumulation_outlet": [
            "accumulation_flux",
            "drainage_flux_history_m3_s",
            "drainage_flux_m3_s",
        ],
        "outflow_drain": [
            "drainage_flux_history_m3_s",
            "drainage_flux_m3_s",
        ],
        "surface_excess_flux": [
            "surface_excess_total_m3_s",
            "surface_threshold_total_m3_s",
            "saturation_excess_total_m3_s",
            "saturation_excess_history_m_s",
        ],
        "surface_excess_rate": [
            "saturation_excess_history_m_s",
        ],
        "surface_excess_map": [
            "saturation_excess_history_m_s",
        ],
        "head": ["watertable_elevation"],
        "depth": ["watertable_depth"],
        "drainage_flux": ["drainage_flux_history_m3_s", "drainage_flux_m3_s"],
    }
    candidates.extend(alias_map.get(lowered, []))
    return tuple(dict.fromkeys(candidates))


def _native_unit_for_variable(variable_name: str) -> str:
    """Return a best-effort native unit label for known disk variables."""
    key = variable_name.strip().lower()
    if key in {"outlet_flux", "outlet_flux_m3_s"}:
        return "m3/s"
    if key in {
        "surface_excess_flux",
        "surface_excess_total_m3_s",
        "surface_threshold_total_m3_s",
        "saturation_excess_total_m3_s",
    }:
        return "m3/s"
    if key in {"watertable_elevation", "head"}:
        return "m"
    if key == "watertable_depth":
        return "m"
    if key in {"surface_excess_rate", "surface_excess_map"}:
        return "m/day"
    if key in {"accumulation_flux", "outflow_drain", "seepage_areas"}:
        return "m/day"
    if key.endswith("_m3_s") or "_m3_s" in key:
        return "m3/s"
    if key.endswith("_m_s") or "_m_s" in key:
        return "m/s"
    return ""


def _is_canonical_outlet_flux(variable_name: str) -> bool:
    key = variable_name.strip().lower()
    return key in {"outlet_flux", "outlet_flux_m3_s"}


def _is_canonical_surface_excess_flux(variable_name: str) -> bool:
    key = variable_name.strip().lower()
    return key in {"surface_excess_flux", "surface_excess_total_m3_s"}


def _convert_accumulation_rate_to_m3_s(
    *,
    value_m_per_day: float,
    cell_area_m2: float,
) -> float:
    """Convert one accumulation depth-rate to a volumetric cell outflow."""
    return (float(value_m_per_day) * float(cell_area_m2)) / 86400.0


def _convert_flux_m3_s_to_depth_m_per_day(
    *,
    value_m3_s: float,
    cell_area_m2: float,
) -> float:
    """Convert one volumetric cell flux to a depth-rate over that cell."""
    return (float(value_m3_s) / float(cell_area_m2)) * 86400.0


def _convert_rate_m_s_to_m_per_day(*, value_m_s: float) -> float:
    """Convert one depth-rate from `m/s` to `m/day`."""
    return float(value_m_s) * 86400.0


_NODATA_SENTINELS = (-9999.0, -99999.0, -999999.0)


def is_nodata_value(value: Any) -> bool:
    """Return True for common HydroModPy numeric sentinel values."""
    try:
        parsed = float(value)
    except Exception:
        return False
    if not math.isfinite(parsed):
        return True
    return any(
        math.isclose(parsed, sentinel, rel_tol=0.0, abs_tol=1.0e-6)
        for sentinel in _NODATA_SENTINELS
    )


__all__ = ("is_nodata_value",)
