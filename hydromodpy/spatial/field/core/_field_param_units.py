"""Unit aliases and normalization for field-parameter configuration."""

from __future__ import annotations

from typing import Annotated

from pydantic import BeforeValidator

from hydromodpy.core.units.hydraulic_conductivity import (
    M_PER_S_CANONICAL_UNITS,
    normalize_m_per_s_unit,
)

SUPPORTED_PARAMETER_UNITS = ("-", *M_PER_S_CANONICAL_UNITS, "m-1", "cm-1")

_UNIT_ALIASES = {
    "-": "-",
    "1": "-",
    "none": "-",
    "dimensionless": "-",
    "unitless": "-",
    "m-1": "m-1",
    "1/m": "m-1",
    "m^-1": "m-1",
    "cm-1": "cm-1",
    "1/cm": "cm-1",
    "cm^-1": "cm-1",
}


def normalize_unit_token(value: str | None) -> str | None:
    """Normalize one user unit token to canonical representation."""
    if value is None:
        return None
    token = str(value).strip().lower().replace(" ", "")
    if token == "":
        raise ValueError("field.unit cannot be empty when provided")
    if token in _UNIT_ALIASES:
        return _UNIT_ALIASES[token]
    try:
        return normalize_m_per_s_unit(token)
    except ValueError:
        allowed = ", ".join(SUPPORTED_PARAMETER_UNITS)
        raise ValueError(f"Unsupported field.unit '{value}'. Allowed: {allowed}") from None


UnitStr = Annotated[str | None, BeforeValidator(normalize_unit_token)]
"""Optional unit token normalised against ``SUPPORTED_PARAMETER_UNITS``."""
