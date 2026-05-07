"""Top-level solver selection configuration."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.solver.base import registry


class SolverConfig(HydroModelBase):
    """Configuration block defining the active groundwater solver engine."""

    solver_engine: Annotated[str, Profile.USER] = Field(
        default="modflownwt",
        description="Groundwater flow solver backend registered for the 'flow' process.",
    )

    @field_validator("solver_engine", mode="before")
    @classmethod
    def _validate_solver_engine(cls, value: object) -> str:
        raw = getattr(value, "value", value)
        cleaned = str(raw).strip().lower()
        if cleaned == "":
            raise ValueError("solver.solver_engine cannot be empty.")
        return cleaned

    def model_post_init(self, context: object) -> None:
        super().model_post_init(context)
        registry.load_plugins()
        if not registry.is_supported("flow", self.solver_engine):
            known = ", ".join(name for _, name in registry.pairs_for_process("flow"))
            raise ValueError(
                f"Unknown flow solver '{self.solver_engine}'. Registered flow solvers: {known}."
            )
