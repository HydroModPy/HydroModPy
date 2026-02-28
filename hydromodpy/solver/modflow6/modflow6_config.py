"""Pydantic and runtime configuration for MODFLOW 6 expert parameters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.config.param_level import ParamLevel
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_config import VerticalGridConfig
from hydromodpy.solver.utils.temporal.tmesh_config import TMeshConfigModel


class Modflow6RuntimeConfig(BaseModel):
    """Expert runtime settings used to build and solve MODFLOW 6 packages."""

    model_config = ConfigDict(extra="forbid")

    mf6_executable_name: Annotated[str, ParamLevel("expert")] = Field(
        default="mf6",
        description="MODFLOW 6 executable name or absolute path.",
    )
    mf6_ims_complexity: Annotated[str, ParamLevel("expert")] = Field(
        default="COMPLEX",
        description="IMS complexity keyword for MODFLOW 6 (e.g. SIMPLE, MODERATE, COMPLEX).",
    )
    mf_verbose: Annotated[bool, ParamLevel("expert")] = Field(
        default=False,
        description="Enable verbose FloPy logging for MODFLOW 6 setup and execution.",
    )


class Modflow6ProcessSpecificConfig(BaseModel):
    """Process-specific parameters used by selected MODFLOW 6 packages."""

    model_config = ConfigDict(extra="forbid")

    vka: Annotated[float, ParamLevel("expert")] = Field(
        default=1.0,
        description="Vertical anisotropy factor used to derive k33 from k.",
    )


class Modflow6Config(BaseModel):
    """Expert-level MODFLOW 6 configuration organized by concern."""

    model_config = ConfigDict(extra="forbid")

    runtime: Annotated[Modflow6RuntimeConfig, ParamLevel("expert")] = Field(
        default_factory=Modflow6RuntimeConfig,
        description="MODFLOW 6 runtime options.",
    )
    process_specific: Annotated[Modflow6ProcessSpecificConfig, ParamLevel("expert")] = Field(
        default_factory=Modflow6ProcessSpecificConfig,
        description="Process-specific controls for MODFLOW 6 flow packages.",
    )
    sgrid: Annotated[VerticalGridConfig | None, ParamLevel("user")] = Field(
        default=None,
        description="Optional vertical discretization payload as VerticalGridConfig.",
    )
    tgrid: Annotated[TMeshConfigModel | None, ParamLevel("user")] = Field(
        default=None,
        description="Optional temporal discretization payload as TMeshConfigModel.",
    )


def _coerce_modflow6_config(
    config: Modflow6Config | Mapping[str, object] | None = None,
) -> Modflow6Config:
    if config is None:
        return Modflow6Config()
    if isinstance(config, Modflow6Config):
        return config
    if isinstance(config, Mapping):
        return Modflow6Config.model_validate(dict(config))
    raise TypeError("modflow6_config must be None, Modflow6Config, or a mapping of values")


@dataclass(frozen=True)
class Modflow6RuntimeParams:
    """Runtime container for MODFLOW 6 package settings."""

    mf6_executable_name: str = "mf6"
    mf6_ims_complexity: str = "COMPLEX"
    mf_verbose: bool = False


@dataclass(frozen=True)
class Modflow6ProcessSpecificParams:
    """Runtime container for process-specific MODFLOW 6 settings."""

    vka: float = 1.0


@dataclass(frozen=True)
class Modflow6SpecifParams:
    """Runtime container grouped by MODFLOW 6 configuration section."""

    runtime: Modflow6RuntimeParams = Modflow6RuntimeParams()
    process_specific: Modflow6ProcessSpecificParams = Modflow6ProcessSpecificParams()
    sgrid: VerticalGridConfig | None = None
    tgrid: TMeshConfigModel | None = None

    @classmethod
    def from_config(
        cls,
        config: Modflow6Config | Mapping[str, object] | None = None,
    ) -> "Modflow6SpecifParams":
        validated = _coerce_modflow6_config(config)
        return cls(
            runtime=Modflow6RuntimeParams(**validated.runtime.model_dump()),
            process_specific=Modflow6ProcessSpecificParams(
                **validated.process_specific.model_dump()
            ),
            sgrid=validated.sgrid,
            tgrid=validated.tgrid,
        )
