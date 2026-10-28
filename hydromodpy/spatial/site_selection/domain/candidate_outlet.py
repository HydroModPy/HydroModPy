"""One candidate outlet of a site selection, whatever produced it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "CandidateOutlet",
]


@dataclass(frozen=True)
class CandidateOutlet:
    """One candidate outlet considered by the site-selection workflow."""

    candidate_id: str
    x: float
    y: float
    crs: str
    source: str
    source_feature_id: str = ""
    source_label: str = ""
    priority: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        """Return a CSV/parquet-friendly mapping."""

        return {
            "candidate_id": self.candidate_id,
            "x": self.x,
            "y": self.y,
            "crs": self.crs,
            "source": self.source,
            "source_feature_id": self.source_feature_id,
            "source_label": self.source_label,
            "priority": self.priority,
            "attributes": dict(self.attributes),
        }
