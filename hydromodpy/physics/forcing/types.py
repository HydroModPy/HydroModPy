"""Shared forcing type aliases."""

from __future__ import annotations

from typing import Literal, TypeAlias

SpatialMode: TypeAlias = Literal["auto", "homogeneous", "heterogeneous"]
InterpolationMethod: TypeAlias = Literal["nearest", "linear", "idw"]
FirstClimKeyword: TypeAlias = Literal["mean", "first"]

__all__ = ["FirstClimKeyword", "InterpolationMethod", "SpatialMode"]
