"""Re-export from hydromodpy.forcing for backward compatibility."""

from hydromodpy.forcing import (  # noqa: F401
    ObservedRechargeChronicleRequest,
    RechargeChroniclePayload,
    align_forcing_series_to_simulation_window,
    build_recharge_chronicle_payload,
    build_recharge_series,
    build_runoff_series,
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
    "build_recharge_series",
    "build_runoff_series",
    "build_hydrological_step_series",
    "build_hydrological_year_dates",
    "build_recharge_from_reservoir_chronicle",
    "enforce_annual_precipitation_total",
    "generate_daily_precipitation",
    "make_piecewise_constant_daily_qin",
    "precipitation_to_inflow",
]
