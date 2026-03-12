"""Synthetic hydrological forcing builders."""

from hydromodpy.hydrology.synthetic.forcing import (
    build_hydrological_step_series,
    build_hydrological_year_dates,
    build_recharge_from_reservoir_chronicle,
    enforce_annual_precipitation_total,
    generate_daily_precipitation,
    make_piecewise_constant_daily_qin,
    precipitation_to_inflow,
)

__all__ = [
    "build_hydrological_step_series",
    "build_hydrological_year_dates",
    "build_recharge_from_reservoir_chronicle",
    "enforce_annual_precipitation_total",
    "generate_daily_precipitation",
    "make_piecewise_constant_daily_qin",
    "precipitation_to_inflow",
]
