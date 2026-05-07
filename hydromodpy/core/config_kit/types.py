"""Shared constrained config types and reusable Literal aliases."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field

IdentifierStr = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]

TimePeriodUnit: TypeAlias = Literal["hour", "day", "month", "year"]
"""Calendar period unit used by simulation/time windows."""

CoveragePolicy: TypeAlias = Literal["error", "warn", "ignore"]
"""Reaction policy when input data does not cover a window."""

InterpolationMethod: TypeAlias = Literal["nearest", "linear", "idw"]
"""Spatial interpolation method shared by spatial and physics layers."""

__all__ = [
    "CoveragePolicy",
    "IdentifierStr",
    "InterpolationMethod",
    "TimePeriodUnit",
]
