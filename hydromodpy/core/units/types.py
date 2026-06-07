"""Pydantic-pint annotated types for hydrogeological quantities.

Two flavors are provided:

- ``Length``, ``Area``, ``Volume``, ``Time``, ``FlowRate``, ``Velocity``,
  ``HydraulicConductivity``, ``SpecificStorage``, ``Dimensionless``:
  Pydantic-pint Quantity types. Values keep their pint Quantity wrapper
  (useful for ratio arithmetic / serialization).
- ``LengthMeters``, ``AreaSquareMeters``, ``VolumetricFlowM3PerSecond``,
  ``DurationSeconds``, ``HydraulicConductivityMPerS``: float-valued
  annotated types that accept the same string/number inputs but expose
  a plain ``float`` in the canonical SI unit. Use these on existing
  fields whose downstream consumers expect plain numbers.

This module exports `Annotated` type aliases that can be used directly in
Pydantic v2 models to enforce unit consistency. Each type accepts either a
bare number (interpreted as the canonical SI unit) or a string "<value> <unit>"
that pint can parse; the resulting value is always a pint `Quantity` in the
canonical unit.

Example
-------
>>> from pydantic import BaseModel
>>> from hydromodpy.core.units import HydraulicConductivity
>>> class Aquifer(BaseModel):
...     k: HydraulicConductivity
>>> Aquifer(k="1e-4 m/s").k.to("m/s").magnitude
0.0001
>>> Aquifer(k=1e-4).k.to("m/s").magnitude  # bare number, fallback m/s
0.0001
>>> Aquifer(k="0.36 m/h").k.to("m/s").magnitude  # auto-convert
0.0001

Design notes
------------
- All annotations reuse the shared ``UREG`` registry (see ``registry.py``) so
  that quantities from different fields remain comparable.
- ``BeforeValidator`` coerces bare numeric inputs (``int``/``float``, but NOT
  ``bool``) to the canonical-unit string before handing off to pydantic-pint.
  Important: in an ``Annotated[...]`` chain, later entries wrap earlier ones,
  so ``BeforeValidator`` must be listed **after** ``PydanticPintQuantity`` -
  otherwise pydantic-pint's custom core schema replaces the chain and the
  before-validator never runs.
- ``SpecificYield`` is a plain ``float`` constrained to [0, 1] (it is
  genuinely dimensionless with a physical range) - not a pint Quantity.
- ``Dimensionless`` is the pint way to express a pure-number quantity when the
  pipeline expects a Quantity object regardless.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BeforeValidator, Field, PlainSerializer

from hydromodpy.core.units.registry import UREG


def _coerce_bare_number(unit: str):
    """Build a BeforeValidator that turns bare numbers into ``"{v} {unit}"``."""

    def _coerce(value: Any) -> Any:
        if isinstance(value, bool):
            # bool is a subclass of int; reject explicitly to catch typos.
            raise TypeError("numeric field rejected boolean input")
        if isinstance(value, (int, float)):
            return f"{value} {unit}"
        return value

    return _coerce


def _to_canonical_magnitude(unit: str):
    """Build a PlainSerializer that emits the canonical-unit magnitude.

    Falls back to ``float(value)`` when the value is a bare number, which can
    happen for unvalidated defaults assigned via ``Field(default=...)``.
    """

    def _ser(value: Any) -> Any:
        if value is None:
            return None
        to = getattr(value, "to", None)
        if callable(to):
            return float(value.to(unit).magnitude)
        return float(value)

    return _ser


def _pint_annotation(unit: str):
    """Return the pydantic-pint annotation for the given canonical unit.

    Imported lazily so that merely importing this module does not fail in
    environments where ``pydantic_pint`` is not yet installed.
    """
    from pydantic_pint import PydanticPintQuantity

    return PydanticPintQuantity(unit, ureg=UREG)


# ---------------------------------------------------------------------------
# Length-like types
# ---------------------------------------------------------------------------

Length = Annotated[
    Any,
    _pint_annotation("m"),
    BeforeValidator(_coerce_bare_number("m")),
    PlainSerializer(_to_canonical_magnitude("m"), return_type=float, when_used="unless-none"),
]
"""Length in metres. Accepts ``1.0``, ``"1.0 m"``, ``"100 cm"``, ..."""


Area = Annotated[
    Any,
    _pint_annotation("m**2"),
    BeforeValidator(_coerce_bare_number("m**2")),
    PlainSerializer(_to_canonical_magnitude("m**2"), return_type=float, when_used="unless-none"),
]
"""Area in square metres."""


Volume = Annotated[
    Any,
    _pint_annotation("m**3"),
    BeforeValidator(_coerce_bare_number("m**3")),
    PlainSerializer(_to_canonical_magnitude("m**3"), return_type=float, when_used="unless-none"),
]
"""Volume in cubic metres."""


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

Time = Annotated[
    Any,
    _pint_annotation("s"),
    BeforeValidator(_coerce_bare_number("s")),
    PlainSerializer(_to_canonical_magnitude("s"), return_type=float, when_used="unless-none"),
]
"""Duration in seconds. Accepts ``"1 day"``, ``"3600 s"``, ``86400``, ..."""


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------

FlowRate = Annotated[
    Any,
    _pint_annotation("m**3/s"),
    BeforeValidator(_coerce_bare_number("m**3/s")),
    PlainSerializer(_to_canonical_magnitude("m**3/s"), return_type=float, when_used="unless-none"),
]
"""Volumetric flow rate in m^3/s."""


# ---------------------------------------------------------------------------
# Velocity / flux density
# ---------------------------------------------------------------------------

Velocity = Annotated[
    Any,
    _pint_annotation("m/s"),
    BeforeValidator(_coerce_bare_number("m/s")),
    PlainSerializer(_to_canonical_magnitude("m/s"), return_type=float, when_used="unless-none"),
]
"""Velocity / flux density in m/s. Accepts ``1e-8``, ``"1 mm/day"``, ``"0.36 m/h"``."""


# ---------------------------------------------------------------------------
# Hydraulic parameters
# ---------------------------------------------------------------------------

HydraulicConductivity = Annotated[
    Any,
    _pint_annotation("m/s"),
    BeforeValidator(_coerce_bare_number("m/s")),
    PlainSerializer(_to_canonical_magnitude("m/s"), return_type=float, when_used="unless-none"),
]
"""Hydraulic conductivity (K) in m/s. Accepts ``"1e-4 m/s"``, ``"0.36 m/h"``, ``1e-4``."""


SpecificStorage = Annotated[
    Any,
    _pint_annotation("1/m"),
    BeforeValidator(_coerce_bare_number("1/m")),
    PlainSerializer(_to_canonical_magnitude("1/m"), return_type=float, when_used="unless-none"),
]
"""Specific storage (Ss) in m^-1."""


# SpecificYield is genuinely dimensionless with a physical range [0, 1].
SpecificYield = Annotated[
    float,
    Field(ge=0.0, le=1.0, description="Specific yield (Sy), dimensionless in [0, 1]."),
]
"""Specific yield (Sy), a pure number in [0, 1]."""


# Plain dimensionless Quantity when the pipeline expects a Quantity instance.
Dimensionless = Annotated[
    Any,
    _pint_annotation("dimensionless"),
    BeforeValidator(_coerce_bare_number("dimensionless")),
    PlainSerializer(
        _to_canonical_magnitude("dimensionless"), return_type=float, when_used="unless-none"
    ),
]
"""Dimensionless pint Quantity (``-``)."""


# ---------------------------------------------------------------------------
# SI-float flavors (canonical magnitude). Use when downstream consumers
# expect a plain ``float`` and not a pint Quantity wrapper.
# ---------------------------------------------------------------------------


def _coerce_to_canonical_float(unit: str):
    """Build a BeforeValidator that parses any input into a float in ``unit``."""

    def _safe_to_canonical(quantity: Any) -> float:
        try:
            return float(quantity.to(unit).magnitude)
        except Exception as exc:
            # Re-raise pint dimensional / unit errors as plain ValueError so
            # Pydantic wraps them into a ValidationError.
            raise ValueError(str(exc)) from exc

    def _coerce(value: Any) -> Any:
        if value is None:
            return None
        # Already a pint Quantity? Convert to canonical unit magnitude.
        to = getattr(value, "to", None)
        magnitude = getattr(value, "magnitude", None)
        if callable(to) and magnitude is not None:
            return _safe_to_canonical(value)
        # Numeric input (but not bool): treated as canonical unit magnitude.
        if isinstance(value, bool):
            raise TypeError("numeric field rejected boolean input")
        if isinstance(value, (int, float)):
            return float(value)
        # String input parsed via the shared pint registry.
        if isinstance(value, str):
            token = value.strip()
            if token == "":
                raise ValueError("empty string is not a valid quantity")
            try:
                quantity = UREG(token)
            except Exception as exc:
                raise ValueError(str(exc)) from exc
            mag = getattr(quantity, "magnitude", None)
            if mag is None:
                # Pure dimensionless number parsed as a Number, e.g. "50".
                return float(quantity)
            return _safe_to_canonical(quantity)
        # Mapping like {"value": 1, "unit": "km"}.
        if hasattr(value, "items"):
            payload = dict(value)
            if "value" in payload:
                magnitude_in = float(payload["value"])
                unit_in = str(payload.get("unit", unit))
                try:
                    quantity = UREG.Quantity(magnitude_in, unit_in)
                except Exception as exc:
                    raise ValueError(str(exc)) from exc
                return _safe_to_canonical(quantity)
        raise TypeError(f"unsupported value for canonical-{unit} float: {value!r}")

    return _coerce


LengthMeters = Annotated[
    float,
    BeforeValidator(_coerce_to_canonical_float("m")),
]
"""Length in metres expressed as ``float``. Accepts ``"100 m"``, ``"1 km"``, ``50.0``."""


AreaSquareMeters = Annotated[
    float,
    BeforeValidator(_coerce_to_canonical_float("m**2")),
]
"""Area in m^2 expressed as ``float``."""


VolumetricFlowM3PerSecond = Annotated[
    float,
    BeforeValidator(_coerce_to_canonical_float("m**3/s")),
]
"""Volumetric flow rate in m^3/s expressed as ``float``."""


DurationSeconds = Annotated[
    float,
    BeforeValidator(_coerce_to_canonical_float("s")),
]
"""Duration in seconds expressed as ``float``. Accepts ``"1 day"``, ``"3600 s"``."""


HydraulicConductivityMPerS = Annotated[
    float,
    BeforeValidator(_coerce_to_canonical_float("m/s")),
]
"""Hydraulic conductivity in m/s expressed as ``float``."""


__all__ = [
    "Area",
    "AreaSquareMeters",
    "Dimensionless",
    "DurationSeconds",
    "FlowRate",
    "HydraulicConductivity",
    "HydraulicConductivityMPerS",
    "Length",
    "LengthMeters",
    "SpecificStorage",
    "SpecificYield",
    "Time",
    "Velocity",
    "Volume",
    "VolumetricFlowM3PerSecond",
]
