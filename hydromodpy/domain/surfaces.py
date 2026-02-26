from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Surfaces:
    """Container for top and bottom surfaces of the modeled domain."""

    aquifer_top: Any
    aquifer_bottom: Any
