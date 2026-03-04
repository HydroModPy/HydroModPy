"""Declarative simulation configuration models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SimulationProcessConfig(BaseModel):
    """One requested process entry under ``[[simulation.process]]``."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        description=(
            "User-facing identifier for the process. "
            "This id is required and must be unique within the simulation."
        ),
    )
    type: Literal["flow", "transport"] = Field(
        description="Requested process family executed by the launcher."
    )
    solvers: list[str] = Field(
        min_length=1,
        description=(
            "Ordered list of active solver names for this process. Each listed "
            "solver is executed in order."
        ),
    )

    @field_validator("solvers")
    @classmethod
    def _validate_solvers(cls, value: list[str]) -> list[str]:
        cleaned = [solver.strip() for solver in value if solver and solver.strip()]
        if not cleaned:
            raise ValueError("At least one non-empty solver name is required.")
        return cleaned


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
            "[[simulation.process]]. At most one ``flow`` and one "
            "``transport`` process are supported."
        ),
    )

    @field_validator("process")
    @classmethod
    def _validate_unique_process_types(
        cls,
        value: list[SimulationProcessConfig],
    ) -> list[SimulationProcessConfig]:
        seen_types: set[str] = set()
        for process_cfg in value:
            if process_cfg.type in seen_types:
                raise ValueError(
                    "At most one process of each type is supported. "
                    f"Duplicate '{process_cfg.type}' process found."
                )
            seen_types.add(process_cfg.type)
        return value

    def has_processes(self) -> bool:
        """Return True when the simulation explicitly declares processes."""
        return bool(self.process)
