"""Station location contract."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StationLocation:
    """Immutable point location for a sensor or station."""

    id: str
    x: float
    y: float
    crs: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "x": self.x, "y": self.y, "crs": self.crs, **self.metadata}
