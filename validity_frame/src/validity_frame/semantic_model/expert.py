# validity_frame/src/validity_frame/semantic_model/expert.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ExpertVerdict(str, Enum):
    ACCEPT = "Accept"
    REJECT = "Reject"
    PENDING = "Pending"


@dataclass
class ExpertAnnotation:
    """α_expert — jugement expert (niveau de fidélité P_2)."""

    verdict: ExpertVerdict
    reason: str
    annotator: str = "unknown"
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    confidence: float | None = None  # 0.0 – 1.0
    annotations: dict[str, Any] = field(default_factory=dict)
