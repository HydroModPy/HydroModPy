"""Forcing builders: transform raw data into process-ready inputs.

This package sits between data managers (which load raw data) and
process objects (Flow, Transport) that consume forcing payloads.
It handles unit conversion, temporal alignment, and aggregation modes.
"""

from hydromodpy.forcing.recharge_bridge import (
    build_recharge_series,
    build_runoff_series,
)
from hydromodpy.forcing.recharge_chronicle import (
    ObservedRechargeChronicleRequest,
    RechargeChroniclePayload,
    align_forcing_series_to_simulation_window,
    build_recharge_chronicle_payload,
)

__all__ = [
    "ObservedRechargeChronicleRequest",
    "RechargeChroniclePayload",
    "align_forcing_series_to_simulation_window",
    "build_recharge_chronicle_payload",
    "build_recharge_series",
    "build_runoff_series",
]
