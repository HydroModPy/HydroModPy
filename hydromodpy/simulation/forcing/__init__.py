"""Shared forcing builders used by simulation launchers."""

from hydromodpy.simulation.forcing.recharge_chronicle import (
    ObservedRechargeChronicleRequest,
    RechargeChroniclePayload,
    align_forcing_series_to_simulation_window,
    build_recharge_chronicle_payload,
)
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
    "ObservedRechargeChronicleRequest",
    "RechargeChroniclePayload",
    "align_forcing_series_to_simulation_window",
    "build_recharge_chronicle_payload",
    "build_hydrological_step_series",
    "build_hydrological_year_dates",
    "build_recharge_from_reservoir_chronicle",
    "enforce_annual_precipitation_total",
    "generate_daily_precipitation",
    "make_piecewise_constant_daily_qin",
    "precipitation_to_inflow",
]
