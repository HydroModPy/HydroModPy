"""Unit parsing and formatting helpers.

This package exposes two complementary layers:

1. Legacy conversion helpers (``convert_to_m``, ``parse_to_m_per_s``, ...)
   used throughout the existing codebase. They remain available and will be
   migrated module-by-module to pint.
2. Pint-based annotated types for Pydantic models
   (:data:`HydraulicConductivity`, :data:`SpecificYield`, ...) sitting on top
   of the shared registry :data:`UREG`. New code should prefer the pint types.
"""

from hydromodpy.core.units.hydraulic_conductance import (
    M2_PER_S_CANONICAL_UNITS,
    convert_to_m2_per_s,
    factor_to_m2_per_s,
    normalize_m2_per_s_unit,
    parse_to_m2_per_s,
)
from hydromodpy.core.units.hydraulic_conductivity import (
    M_PER_S_CANONICAL_UNITS,
    convert_payload_to_m_per_s,
    convert_to_m_per_s,
    factor_to_m_per_s,
    normalize_m_per_s_unit,
    parse_to_m_per_s,
)
from hydromodpy.core.units.length import (
    LENGTH_CANONICAL_UNITS,
    convert_payload_to_m,
    convert_to_m,
    factor_to_m,
    format_length_from_m,
    normalize_length_unit,
    parse_length_to_m,
    parse_to_m,
)
from hydromodpy.core.units.parse import (
    canonical_unit_short_form,
    check_unit_compatible,
    parse_to_canonical_magnitude,
)
from hydromodpy.core.units.radiation import (
    RADIATION_CANONICAL_UNITS,
    convert_to_w_per_m2,
    factor_to_w_per_m2,
    normalize_radiation_unit,
)
from hydromodpy.core.units.registry import UREG, get_registry
from hydromodpy.core.units.scalar import canonical_unit_token, parse_scalar_and_unit
from hydromodpy.core.units.time import (
    TIME_CANONICAL_UNITS,
    convert_seconds_to_unit,
    convert_to_seconds,
    factor_to_seconds,
    normalize_time_unit,
    timedelta_to_seconds,
    to_modflow6_time_units,
    to_modflow_itmuni,
    to_pandas_timedelta_unit,
)
from hydromodpy.core.units.types import (
    Area,
    Dimensionless,
    FlowRate,
    HydraulicConductivity,
    Length,
    SpecificStorage,
    SpecificYield,
    Time,
    Volume,
)
from hydromodpy.core.units.volumetric_flow import (
    M3_PER_S_CANONICAL_UNITS,
    convert_to_m3_per_s,
    factor_to_m3_per_s,
    normalize_m3_per_s_unit,
    parse_to_m3_per_s,
)

__all__ = [
    # Pint registry + annotated types (new API)
    "UREG",
    "get_registry",
    "Area",
    "Dimensionless",
    "FlowRate",
    "HydraulicConductivity",
    "Length",
    "SpecificStorage",
    "SpecificYield",
    "Time",
    "Volume",
    # Legacy conversion helpers
    "M3_PER_S_CANONICAL_UNITS",
    "M2_PER_S_CANONICAL_UNITS",
    "M_PER_S_CANONICAL_UNITS",
    "LENGTH_CANONICAL_UNITS",
    "TIME_CANONICAL_UNITS",
    "canonical_unit_short_form",
    "canonical_unit_token",
    "check_unit_compatible",
    "parse_to_canonical_magnitude",
    "convert_payload_to_m",
    "convert_payload_to_m_per_s",
    "convert_to_m",
    "convert_to_m2_per_s",
    "convert_to_m3_per_s",
    "convert_seconds_to_unit",
    "convert_to_m_per_s",
    "convert_to_seconds",
    "factor_to_m",
    "factor_to_m2_per_s",
    "factor_to_m3_per_s",
    "factor_to_m_per_s",
    "factor_to_seconds",
    "factor_to_w_per_m2",
    "format_length_from_m",
    "normalize_length_unit",
    "normalize_m2_per_s_unit",
    "normalize_m3_per_s_unit",
    "normalize_m_per_s_unit",
    "normalize_radiation_unit",
    "normalize_time_unit",
    "parse_length_to_m",
    "parse_to_m",
    "parse_to_m2_per_s",
    "parse_to_m3_per_s",
    "parse_scalar_and_unit",
    "parse_to_m_per_s",
    "timedelta_to_seconds",
    "to_modflow6_time_units",
    "to_modflow_itmuni",
    "to_pandas_timedelta_unit",
]
