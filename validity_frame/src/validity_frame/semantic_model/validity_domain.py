from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidityDomain:
    """ZM = ⟨Z_V, Z_C, Z_I, Z_T, Z_Inf⟩"""

    Z_V: list[Any] = field(default_factory=list)  # région validée
    Z_C: list[Any] = field(default_factory=list)  # région calibrée
    Z_I: list[Any] = field(default_factory=list)  # région invalide
    Z_T: list[Any] = field(default_factory=list)  # région théorique
    Z_Inf: list[Any] = field(default_factory=list)  # région de validité inférée
