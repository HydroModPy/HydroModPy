"""Top-level solver selection configuration."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

BUILTIN_BACKENDS: tuple[str, ...] = ("modflow6", "modflow_nwt", "boussinesq")


class _SolverBackendBase(HydroModelBase):
    """Shared base for discriminated solver backend selectors."""


class Modflow6Backend(_SolverBackendBase):
    """Select the MODFLOW 6 flow backend."""

    backend: Annotated[Literal["modflow6"], Profile.USER] = Field(
        default="modflow6",
        description="Discriminator tag selecting the MODFLOW 6 flow backend.",
    )


class ModflowNwtBackend(_SolverBackendBase):
    """Select the MODFLOW-NWT flow backend."""

    backend: Annotated[Literal["modflow_nwt"], Profile.USER] = Field(
        default="modflow_nwt",
        description="Discriminator tag selecting the MODFLOW-NWT flow backend.",
    )


class BoussinesqBackend(_SolverBackendBase):
    """Select the Boussinesq flow backend."""

    backend: Annotated[Literal["boussinesq"], Profile.USER] = Field(
        default="boussinesq",
        description="Discriminator tag selecting the Boussinesq flow backend.",
    )


class CustomBackend(_SolverBackendBase):
    """Plugin-registered flow backend identified by a free-form name.

    The discriminator value is the literal string ``"custom"``; the actual
    backend name lives in ``name``. ``SolverConfig.validate_registry()``
    enforces that the name resolves to a registered flow adapter at
    launcher time.
    """

    backend: Annotated[Literal["custom"], Profile.USER] = Field(
        default="custom",
        description="Discriminator tag indicating a plugin-provided flow backend.",
    )
    name: Annotated[str, Profile.USER] = Field(
        ...,
        description="Plugin-registered flow backend name (matches registry).",
    )

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_name(cls, value: object) -> str:
        cleaned = str(getattr(value, "value", value)).strip().lower()
        if cleaned == "":
            raise ValueError("solver.backend.name cannot be empty.")
        return cleaned


SolverBackendConfig: TypeAlias = Annotated[
    Modflow6Backend | ModflowNwtBackend | BoussinesqBackend | CustomBackend,
    Field(
        discriminator="backend",
        description=("Discriminated union of flow solver backends tagged by the 'backend' key."),
    ),
]


class SolverConfig(HydroModelBase):
    """Configuration block defining the active groundwater solver engine.

    The V1 TOML form is ``backend = { backend = "modflow6" }`` for a
    built-in backend, or ``backend = { backend = "custom", name = "x" }``
    for a plugin-registered backend.
    """

    backend: Annotated[SolverBackendConfig, Profile.USER] = Field(
        default_factory=Modflow6Backend,
        description="Active flow backend selector (discriminated union).",
    )

    @property
    def backend_name(self) -> str:
        """Canonical backend name compatible with the solver registry."""
        if isinstance(self.backend, CustomBackend):
            return self.backend.name
        return self.backend.backend

    def validate_registry(self) -> None:
        """Verify the selected engine is registered. Call explicitly from launcher."""
        from hydromodpy.solver.base import registry

        registry.load_plugins()
        engine = self.backend_name
        if not registry.is_supported("flow", engine):
            known = ", ".join(name for _, name in registry.pairs_for_process("flow"))
            raise ValueError(f"Unknown flow solver '{engine}'. Registered flow solvers: {known}.")
