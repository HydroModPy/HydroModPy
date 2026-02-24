"""
Concrete discretization based on per-zone cell fractions.

This implementation corresponds to the current workflow:
- each key (zone/material) has one per-cell weight/fraction array,
- `FieldParam` aggregates values with a weighted average.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:
    from hydromodpy.field.core.field_spatial import FieldDiscretization
except ModuleNotFoundError:  # pragma: no cover - direct script fallback
    from field_spatial import FieldDiscretization  # type: ignore


@dataclass(frozen=True)
class WeightedAverageFieldDiscretization(FieldDiscretization):
    """
    Weighted-average discretization with per-zone fractions on mesh cells.

    Attributes
    ----------
    zone_keys : tuple[str, ...]
        Ordered keys expected in `FieldParam.values_by_key`.
    fractions_by_zone : dict[str, np.ndarray]
        Per-zone fractions on cells (same mesh cell shape for each key).
    """

    zone_keys: tuple[str, ...]
    fractions_by_zone: dict[str, np.ndarray]

    def __post_init__(self):
        super().__post_init__()

        keys = tuple(str(k).strip() for k in self.zone_keys)
        if len(keys) == 0:
            raise ValueError("zone_keys cannot be empty")
        if any(k == "" for k in keys):
            raise ValueError("zone_keys cannot contain empty names")

        raw_map = dict(self.fractions_by_zone)
        normalized: dict[str, np.ndarray] = {}
        for key in keys:
            if key not in raw_map:
                raise ValueError(f"fractions_by_zone is missing key '{key}'")
            normalized[key] = np.asarray(raw_map[key], dtype=float)

        object.__setattr__(self, "zone_keys", keys)
        object.__setattr__(self, "fractions_by_zone", normalized)

    def aggregation_name(self) -> str:
        return "weighted_average"

    def weighted_components(self) -> tuple[tuple[str, ...], dict[str, np.ndarray]]:
        return self.zone_keys, self.fractions_by_zone
