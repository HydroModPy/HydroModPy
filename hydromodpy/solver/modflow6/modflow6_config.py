"""Pydantic and runtime configuration for MODFLOW 6 expert parameters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_config import SolverSGridConfig
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
    mf6_outer_dvclose: Annotated[float, ParamLevel("expert")] = Field(
        default=1e-4,
        gt=0.0,
        description="IMS outer-iteration head-change convergence criterion.",
    )
    mf6_inner_dvclose: Annotated[float, ParamLevel("expert")] = Field(
        default=1e-4,
        gt=0.0,
        description="IMS inner-iteration head-change convergence criterion.",
    )
    mf6_outer_maximum: Annotated[int, ParamLevel("expert")] = Field(
        default=500,
        ge=1,
        description="Maximum number of IMS outer iterations.",
    )
    mf6_inner_maximum: Annotated[int, ParamLevel("expert")] = Field(
        default=500,
        ge=1,
        description="Maximum number of IMS inner iterations.",
    )
    mf6_enable_rewet: Annotated[bool | None, ParamLevel("expert")] = Field(
        default=None,
        description=(
            "Enable NPF cell rewetting. When left to None, HydroModPy "
            "keeps rewetting disabled unless explicitly enabled."
        ),
    )
    mf6_rewet_wetfct: Annotated[float, ParamLevel("expert")] = Field(
        default=0.1,
        gt=0.0,
        description="MF6 NPF rewet WETFCT factor.",
    )
    mf6_rewet_iwetit: Annotated[int, ParamLevel("expert")] = Field(
        default=1,
        ge=1,
        description="MF6 NPF rewet IWETIT interval.",
    )
    mf6_rewet_ihdwet: Annotated[int, ParamLevel("expert")] = Field(
        default=0,
        description="MF6 NPF rewet IHDWET flag.",
    )
    mf6_rewet_wetdry: Annotated[float, ParamLevel("expert")] = Field(
        default=0.1,
        gt=0.0,
        description="MF6 NPF WETDRY threshold used when rewetting is active.",
    )


class Modflow6ProcessSpecificConfig(BaseModel):
    """Process-specific parameters used by selected MODFLOW 6 packages."""

    model_config = ConfigDict(extra="forbid")

    vka: Annotated[float, ParamLevel("expert")] = Field(
        default=1.0,
        description="Vertical anisotropy factor used to derive k33 from k.",
    )
    evt_extinction_depth: Annotated[float, ParamLevel("expert")] = Field(
        default=1.0,
        gt=0.0,
        description="MF6 EVT extinction depth in meters when recharge negatives are routed to EVT.",
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
    sgrid: Annotated[SolverSGridConfig, ParamLevel("user")] = Field(
        default_factory=SolverSGridConfig,
        description="Solver-grid payload split into planar and vertical sections.",
    )
    tgrid: Annotated[TMeshConfigModel | None, ParamLevel("user")] = Field(
        default=None,
        description=(
            "Optional temporal discretization payload as TMeshConfigModel. In "
            "launcher mode, stress periods are driven by [simulation.time]; "
            "this section is mirrored for compatibility and mainly keeps "
            "`firstpersteady`."
        ),
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
class Modflow6SpecifParams:
    """Runtime container grouped by MODFLOW 6 configuration section.

    Uses the validated Pydantic models directly instead of duplicating fields
    into separate frozen dataclasses.
    """

    runtime: Modflow6RuntimeConfig = field(default_factory=Modflow6RuntimeConfig)
    process_specific: Modflow6ProcessSpecificConfig = field(
        default_factory=Modflow6ProcessSpecificConfig,
    )
    sgrid: SolverSGridConfig = field(default_factory=SolverSGridConfig)
    tgrid: TMeshConfigModel | None = None

    @classmethod
    def from_config(
        cls,
        config: Modflow6Config | Mapping[str, object] | None = None,
    ) -> "Modflow6SpecifParams":
        validated = _coerce_modflow6_config(config)
        return cls(
            runtime=validated.runtime,
            process_specific=validated.process_specific,
            sgrid=validated.sgrid,
            tgrid=validated.tgrid,
        )
