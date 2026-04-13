"""Shared descriptors for Boussinesq algebraic formulations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

UnknownLayoutName = Literal["head_only", "head_plus_qex"]
SurfaceClosureName = Literal["regularized_partition", "complementarity"]


@dataclass(frozen=True)
class BoussinesqFormulationSpec:
    """Descriptor for one algebraic formulation of the Boussinesq problem."""

    id: str
    unknown_layout: UnknownLayoutName
    surface_closure: SurfaceClosureName
    steady_residual_label: str
    transient_residual_label: str
    description: str


__all__ = [
    "BoussinesqFormulationSpec",
    "SurfaceClosureName",
    "UnknownLayoutName",
]
