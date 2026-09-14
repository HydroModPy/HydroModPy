from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelStructure:
    """SM = ⟨IM, OM, Par_M, States_M⟩"""

    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    parameters: tuple[str, ...]
    states: tuple[str, ...]


@dataclass(frozen=True)
class PropertyDetail:
    """Structure commune pour une propriété ou un facteur d'influence."""

    id: str
    name: str
    description: str
    unit: str | None = None  # None pour les inconnus/non-mesurables
    min: float | None = None  # None pour les inconnus/non-mesurables
    max: float | None = None  # None pour les inconnus/non-mesurables


@dataclass(frozen=True)
class PropertiesOfInterest:
    """Π_M = ⟨Π_known, Π_unknown⟩"""

    known: tuple[PropertyDetail, ...]  # unit, min, max remplis
    unknown: tuple[PropertyDetail, ...]  # unit, min, max à None


@dataclass(frozen=True)
class InfluenceFactors:
    """Γ_M = ⟨Γ_meas, Γ_nomeas⟩"""

    measurable: tuple[PropertyDetail, ...]  # unit, min, max remplis
    non_measurable: tuple[PropertyDetail, ...]  # unit, min, max à None
