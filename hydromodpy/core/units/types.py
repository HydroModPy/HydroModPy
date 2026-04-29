"""Pydantic-pint annotated types for hydrogeological quantities.

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
    Field(ge=0.0, le=1.0),
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


__all__ = [
    "Area",
    "Dimensionless",
    "FlowRate",
    "HydraulicConductivity",
    "Length",
    "SpecificStorage",
    "SpecificYield",
    "Time",
    "Velocity",
    "Volume",
]
