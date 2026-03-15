"""Forcing builders: transform raw data into process-ready inputs.

This package sits between data managers (which load raw data) and
process objects (Flow, Transport) that consume forcing payloads.
It handles unit conversion, temporal alignment, and aggregation modes.
"""

from hydromodpy.forcing.forcing_bridge import (
    ResolvedForcing,
    _MM_PER_DAY_TO_M_PER_S,
    build_forcing_series,
    extract_homogeneous_series,
    extract_homogeneous_series_from_fields,
    has_located_points,
    resolve_forcing,
)

from hydromodpy.forcing.time_alignment import (
    align_forcing_series_to_simulation_window,
)

__all__ = [
    "ResolvedForcing",
    "_MM_PER_DAY_TO_M_PER_S",
    "align_forcing_series_to_simulation_window",
    "build_forcing_series",
    "extract_homogeneous_series",
    "extract_homogeneous_series_from_fields",
    "has_located_points",
    "resolve_forcing",
]
