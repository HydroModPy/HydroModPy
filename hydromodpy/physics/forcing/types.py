"""Shared forcing type aliases."""

from __future__ import annotations

from typing import Literal, TypeAlias

from hydromodpy.core.config_kit.types import InterpolationMethod

SpatialMode: TypeAlias = Literal["auto", "homogeneous", "heterogeneous"]
FirstClimKeyword: TypeAlias = Literal["mean", "first"]

__all__ = ["FirstClimKeyword", "InterpolationMethod", "SpatialMode"]
