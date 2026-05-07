"""Shared constrained config types and reusable Literal aliases."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BeforeValidator, Field

# ---------------------------------------------------------------------------
# String types
# ---------------------------------------------------------------------------

IdentifierStr = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
"""Snake-case identifier starting with a lowercase letter."""


def _strip(value: object) -> str:
    return str(value).strip()


def _strip_lower(value: object) -> str:
    return str(value).strip().lower()


def _strip_non_empty(value: object) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("value cannot be empty")
    return text


NormalizedStr = Annotated[str, BeforeValidator(_strip)]
"""String stripped of surrounding whitespace."""

NormalizedLowerStr = Annotated[str, BeforeValidator(_strip_lower)]
"""String stripped and lower-cased (use for case-insensitive enums)."""

NonEmptyStr = Annotated[str, BeforeValidator(_strip_non_empty)]
"""Non-empty string after stripping whitespace."""

StripLower = BeforeValidator(_strip_lower)
"""Reusable BeforeValidator to combine with a ``Literal`` for case-insensitive enums."""


# ---------------------------------------------------------------------------
# Numeric domains
# ---------------------------------------------------------------------------

PositiveInt = Annotated[int, Field(gt=0)]
PositiveFloat = Annotated[float, Field(gt=0.0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegativeFloat = Annotated[float, Field(ge=0.0)]
Probability = Annotated[float, Field(ge=0.0, le=1.0)]
"""Float in the closed interval [0, 1]."""

CellSamplingDensity = Annotated[int, Field(ge=2)]
"""Sub-sampling density per cell axis used when rasterising masks."""


# ---------------------------------------------------------------------------
# Domain literals
# ---------------------------------------------------------------------------

TimePeriodUnit: TypeAlias = Literal["hour", "day", "month", "year"]
"""Calendar period unit used by simulation/time windows."""

CoveragePolicy: TypeAlias = Literal["error", "warn", "ignore"]
"""Reaction policy when input data does not cover a window."""

InterpolationMethod: TypeAlias = Literal["nearest", "linear", "idw"]
"""Spatial interpolation method shared by spatial and physics layers."""


__all__ = [
    "CellSamplingDensity",
    "CoveragePolicy",
    "IdentifierStr",
    "InterpolationMethod",
    "NonEmptyStr",
    "NonNegativeFloat",
    "NonNegativeInt",
    "NormalizedLowerStr",
    "NormalizedStr",
    "PositiveFloat",
    "PositiveInt",
    "Probability",
    "StripLower",
    "TimePeriodUnit",
]
