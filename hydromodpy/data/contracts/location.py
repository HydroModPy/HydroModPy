"""Station location contract."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class StationLocation:
    """Immutable point location for a sensor or station."""

    id: str
    x: float
    y: float
    crs: str
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # A location read by pandas carries numpy scalars, and the catalog
        # writes the metadata as JSON, which refuses np.int64 and np.bool_.
        native = {
            key: value.item() if isinstance(value, np.generic) else value
            for key, value in self.metadata.items()
        }
        object.__setattr__(self, "metadata", native)

    def to_dict(self) -> dict:
        return {"id": self.id, "x": self.x, "y": self.y, "crs": self.crs, **self.metadata}
