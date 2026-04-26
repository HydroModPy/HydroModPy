"""Unit parsing and formatting helpers.

Keep the package facade lazy so lightweight imports such as
``hydromodpy.core.units.labels`` do not require the full Pint stack.
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
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
    "M3_PER_S_CANONICAL_UNITS",
    "M2_PER_S_CANONICAL_UNITS",
    "M_PER_S_CANONICAL_UNITS",
    "LENGTH_CANONICAL_UNITS",
    "TIME_CANONICAL_UNITS",
    "RADIATION_CANONICAL_UNITS",
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
    "convert_to_w_per_m2",
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

_LAZY_IMPORTS = {
    "M2_PER_S_CANONICAL_UNITS": "hydromodpy.core.units.hydraulic_conductance:M2_PER_S_CANONICAL_UNITS",
    "convert_to_m2_per_s": "hydromodpy.core.units.hydraulic_conductance:convert_to_m2_per_s",
    "factor_to_m2_per_s": "hydromodpy.core.units.hydraulic_conductance:factor_to_m2_per_s",
    "normalize_m2_per_s_unit": "hydromodpy.core.units.hydraulic_conductance:normalize_m2_per_s_unit",
    "parse_to_m2_per_s": "hydromodpy.core.units.hydraulic_conductance:parse_to_m2_per_s",
    "M_PER_S_CANONICAL_UNITS": "hydromodpy.core.units.hydraulic_conductivity:M_PER_S_CANONICAL_UNITS",
    "convert_payload_to_m_per_s": "hydromodpy.core.units.hydraulic_conductivity:convert_payload_to_m_per_s",
    "convert_to_m_per_s": "hydromodpy.core.units.hydraulic_conductivity:convert_to_m_per_s",
    "factor_to_m_per_s": "hydromodpy.core.units.hydraulic_conductivity:factor_to_m_per_s",
    "normalize_m_per_s_unit": "hydromodpy.core.units.hydraulic_conductivity:normalize_m_per_s_unit",
    "parse_to_m_per_s": "hydromodpy.core.units.hydraulic_conductivity:parse_to_m_per_s",
    "LENGTH_CANONICAL_UNITS": "hydromodpy.core.units.length:LENGTH_CANONICAL_UNITS",
    "convert_payload_to_m": "hydromodpy.core.units.length:convert_payload_to_m",
    "convert_to_m": "hydromodpy.core.units.length:convert_to_m",
    "factor_to_m": "hydromodpy.core.units.length:factor_to_m",
    "format_length_from_m": "hydromodpy.core.units.length:format_length_from_m",
    "normalize_length_unit": "hydromodpy.core.units.length:normalize_length_unit",
    "parse_length_to_m": "hydromodpy.core.units.length:parse_length_to_m",
    "parse_to_m": "hydromodpy.core.units.length:parse_to_m",
    "canonical_unit_short_form": "hydromodpy.core.units.parse:canonical_unit_short_form",
    "check_unit_compatible": "hydromodpy.core.units.parse:check_unit_compatible",
    "parse_to_canonical_magnitude": "hydromodpy.core.units.parse:parse_to_canonical_magnitude",
    "RADIATION_CANONICAL_UNITS": "hydromodpy.core.units.radiation:RADIATION_CANONICAL_UNITS",
    "convert_to_w_per_m2": "hydromodpy.core.units.radiation:convert_to_w_per_m2",
    "factor_to_w_per_m2": "hydromodpy.core.units.radiation:factor_to_w_per_m2",
    "normalize_radiation_unit": "hydromodpy.core.units.radiation:normalize_radiation_unit",
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
    "Dimensionless": "hydromodpy.core.units.types:Dimensionless",
    "FlowRate": "hydromodpy.core.units.types:FlowRate",
    "HydraulicConductivity": "hydromodpy.core.units.types:HydraulicConductivity",
    "Length": "hydromodpy.core.units.types:Length",
    "SpecificStorage": "hydromodpy.core.units.types:SpecificStorage",
    "SpecificYield": "hydromodpy.core.units.types:SpecificYield",
    "Time": "hydromodpy.core.units.types:Time",
    "Volume": "hydromodpy.core.units.types:Volume",
    "M3_PER_S_CANONICAL_UNITS": "hydromodpy.core.units.volumetric_flow:M3_PER_S_CANONICAL_UNITS",
    "convert_to_m3_per_s": "hydromodpy.core.units.volumetric_flow:convert_to_m3_per_s",
    "factor_to_m3_per_s": "hydromodpy.core.units.volumetric_flow:factor_to_m3_per_s",
    "normalize_m3_per_s_unit": "hydromodpy.core.units.volumetric_flow:normalize_m3_per_s_unit",
    "parse_to_m3_per_s": "hydromodpy.core.units.volumetric_flow:parse_to_m3_per_s",
}


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
