"""Resolved simulation plan objects."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProcessRun:
    """One concrete execution unit: a process resolved with one solver."""

    id: str
    process_id: str
    process_type: str
    solver: str
    depends_on: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SimulationPlan:
    """Ordered list of concrete process runs ready for execution."""

    name: str
    description: str
    runs: tuple[ProcessRun, ...] = field(default_factory=tuple)

    def is_empty(self) -> bool:
        """Return True when no process run was planned."""
        return not self.runs
