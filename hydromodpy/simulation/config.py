"""Declarative simulation configuration models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SimulationProcessConfig(BaseModel):
    """One requested process entry under ``[[simulation.process]]``."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(
        default=None,
        description=(
            "Optional user-facing identifier for the process. "
            "If omitted, a deterministic id is derived from the process type."
        ),
    )
    type: Literal["flow", "transport"] = Field(
        description="Requested process family executed by the launcher."
    )
    solvers: list[str] = Field(
        min_length=1,
        description=(
            "Ordered list of active solver names for this process. "
            "Each listed solver is executed."
        ),
    )

    @field_validator("solvers")
    @classmethod
    def _validate_solvers(cls, value: list[str]) -> list[str]:
        cleaned = [solver.strip() for solver in value if solver and solver.strip()]
        if not cleaned:
            raise ValueError("At least one non-empty solver name is required.")
        return cleaned

    def resolved_id(self, index: int) -> str:
        """Return the explicit id or derive a stable fallback identifier."""
        if self.id:
            return self.id
        return f"{self.type}_{index}"


class SimulationConfig(BaseModel):
    """Minimal orchestration block declared under ``[simulation]``."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", description="Human-readable simulation name.")
    description: str = Field(
        default="",
        description="Short free-text description of the simulation intent.",
    )
    process: list[SimulationProcessConfig] = Field(
        default_factory=list,
        description=(
            "Ordered list of requested processes loaded from "
            "[[simulation.process]]."
        ),
    )

    def has_processes(self) -> bool:
        """Return True when the simulation explicitly declares processes."""
        return bool(self.process)
