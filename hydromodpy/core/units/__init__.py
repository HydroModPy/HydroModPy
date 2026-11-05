"""Unit parsing and formatting helpers.

Lazy facade. Lightweight imports such as ``hydromodpy.core.units.labels``
do not require loading the full Pint stack.
"""

from __future__ import annotations

from importlib import import_module

_LAZY_IMPORTS: dict[str, str] = {
    "format_length_from_m": "hydromodpy.core.units.labels:format_length_from_m",
    "canonical_unit_short_form": "hydromodpy.core.units.parse:canonical_unit_short_form",
    "check_unit_compatible": "hydromodpy.core.units.parse:check_unit_compatible",
    "convert_between_units": "hydromodpy.core.units.parse:convert_between_units",
    "parse_to_canonical_magnitude": "hydromodpy.core.units.parse:parse_to_canonical_magnitude",
    "LENGTH_CANONICAL_UNITS": "hydromodpy.core.units.quantities:LENGTH_CANONICAL_UNITS",
    "M2_PER_S_CANONICAL_UNITS": "hydromodpy.core.units.quantities:M2_PER_S_CANONICAL_UNITS",
    "M3_PER_S_CANONICAL_UNITS": "hydromodpy.core.units.quantities:M3_PER_S_CANONICAL_UNITS",
    "M_PER_S_CANONICAL_UNITS": "hydromodpy.core.units.quantities:M_PER_S_CANONICAL_UNITS",
    "PER_S_CANONICAL_UNITS": "hydromodpy.core.units.quantities:PER_S_CANONICAL_UNITS",
    "RADIATION_CANONICAL_UNITS": "hydromodpy.core.units.quantities:RADIATION_CANONICAL_UNITS",
    "convert_payload_to_m": "hydromodpy.core.units.quantities:convert_payload_to_m",
    "convert_payload_to_m_per_s": "hydromodpy.core.units.quantities:convert_payload_to_m_per_s",
    "convert_to_m": "hydromodpy.core.units.quantities:convert_to_m",
    "convert_to_m2_per_s": "hydromodpy.core.units.quantities:convert_to_m2_per_s",
    "convert_to_m3_per_s": "hydromodpy.core.units.quantities:convert_to_m3_per_s",
    "convert_to_m_per_s": "hydromodpy.core.units.quantities:convert_to_m_per_s",
    "convert_to_per_s": "hydromodpy.core.units.quantities:convert_to_per_s",
    "convert_to_w_per_m2": "hydromodpy.core.units.quantities:convert_to_w_per_m2",
    "factor_to_m": "hydromodpy.core.units.quantities:factor_to_m",
    "factor_to_m2_per_s": "hydromodpy.core.units.quantities:factor_to_m2_per_s",
    "factor_to_m3_per_s": "hydromodpy.core.units.quantities:factor_to_m3_per_s",
    "factor_to_m_per_s": "hydromodpy.core.units.quantities:factor_to_m_per_s",
    "factor_to_per_s": "hydromodpy.core.units.quantities:factor_to_per_s",
    "factor_to_w_per_m2": "hydromodpy.core.units.quantities:factor_to_w_per_m2",
    "normalize_length_unit": "hydromodpy.core.units.quantities:normalize_length_unit",
    "normalize_m2_per_s_unit": "hydromodpy.core.units.quantities:normalize_m2_per_s_unit",
    "normalize_m3_per_s_unit": "hydromodpy.core.units.quantities:normalize_m3_per_s_unit",
    "normalize_m_per_s_unit": "hydromodpy.core.units.quantities:normalize_m_per_s_unit",
    "normalize_per_s_unit": "hydromodpy.core.units.quantities:normalize_per_s_unit",
    "normalize_radiation_unit": "hydromodpy.core.units.quantities:normalize_radiation_unit",
    "parse_to_m": "hydromodpy.core.units.quantities:parse_to_m",
    "parse_to_m2_per_s": "hydromodpy.core.units.quantities:parse_to_m2_per_s",
    "parse_to_m3_per_s": "hydromodpy.core.units.quantities:parse_to_m3_per_s",
    "parse_to_m_per_s": "hydromodpy.core.units.quantities:parse_to_m_per_s",
    "parse_to_per_s": "hydromodpy.core.units.quantities:parse_to_per_s",
    "UREG": "hydromodpy.core.units.registry:UREG",
    "get_registry": "hydromodpy.core.units.registry:get_registry",
    "canonical_unit_token": "hydromodpy.core.units.scalar:canonical_unit_token",
    "parse_scalar_and_unit": "hydromodpy.core.units.scalar:parse_scalar_and_unit",
    "TIME_CANONICAL_UNITS": "hydromodpy.core.units.time:TIME_CANONICAL_UNITS",
    "convert_seconds_to_unit": "hydromodpy.core.units.time:convert_seconds_to_unit",
    "convert_to_seconds": "hydromodpy.core.units.time:convert_to_seconds",
    "factor_to_seconds": "hydromodpy.core.units.time:factor_to_seconds",
    "normalize_time_unit": "hydromodpy.core.units.time:normalize_time_unit",
    "timedelta_to_seconds": "hydromodpy.core.units.time:timedelta_to_seconds",
    "to_modflow6_time_units": "hydromodpy.core.units.time:to_modflow6_time_units",
    "to_modflow_itmuni": "hydromodpy.core.units.time:to_modflow_itmuni",
    "to_pandas_timedelta_unit": "hydromodpy.core.units.time:to_pandas_timedelta_unit",
    "Area": "hydromodpy.core.units.types:Area",
    "AreaSquareMeters": "hydromodpy.core.units.types:AreaSquareMeters",
    "Dimensionless": "hydromodpy.core.units.types:Dimensionless",
    "DurationSeconds": "hydromodpy.core.units.types:DurationSeconds",
    "FlowRate": "hydromodpy.core.units.types:FlowRate",
    "FluxDensityMPerS": "hydromodpy.core.units.types:FluxDensityMPerS",
    "HydraulicConductivity": "hydromodpy.core.units.types:HydraulicConductivity",
    "HydraulicConductivityMPerS": "hydromodpy.core.units.types:HydraulicConductivityMPerS",
    "Length": "hydromodpy.core.units.types:Length",
    "LengthMeters": "hydromodpy.core.units.types:LengthMeters",
    "SpecificStorage": "hydromodpy.core.units.types:SpecificStorage",
    "SpecificYield": "hydromodpy.core.units.types:SpecificYield",
    "Time": "hydromodpy.core.units.types:Time",
    "Velocity": "hydromodpy.core.units.types:Velocity",
    "Volume": "hydromodpy.core.units.types:Volume",
    "VolumetricFlowM3PerSecond": "hydromodpy.core.units.types:VolumetricFlowM3PerSecond",
}

__all__ = list(_LAZY_IMPORTS.keys())


def __getattr__(name: str):
    try:
        target = _LAZY_IMPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module_path, attr_name = target.split(":", 1)
    module = import_module(module_path)
    attr = getattr(module, attr_name)
    globals()[name] = attr
    return attr
