from __future__ import annotations

from dataclasses import dataclass,field
from datetime import datetime,timezone
from typing import Any

@dataclass(slots=True)
class Context:
    run_id: str | None = None
    solver: str | None = None
    iteration: int | None = None
    workspace: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class ExecutionContext:
    run_id: str | None = None
    solver: str | None = None
    iteration: int | None = None
    workspace: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)