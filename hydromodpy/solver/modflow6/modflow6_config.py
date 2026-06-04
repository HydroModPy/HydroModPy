"""Pydantic and runtime configuration for MODFLOW 6 expert parameters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import PositiveFloat, PositiveInt
from hydromodpy.discretization.time.tmesh_config import TMeshConfig
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_config import SolverSGridConfig


class Modflow6RuntimeConfig(HydroModelBase):
    """Expert runtime settings used to build and solve MODFLOW 6 packages."""

    mf6_executable_name: Annotated[str, Profile.EXPERT] = Field(
        default="mf6",
        description="MODFLOW 6 executable name or absolute path.",
    )
    mf6_ims_complexity: Annotated[Literal["SIMPLE", "MODERATE", "COMPLEX"], Profile.EXPERT] = Field(
        default="COMPLEX",
        description="IMS complexity preset for MODFLOW 6: SIMPLE, MODERATE, or COMPLEX.",
    )
    mf_verbose: Annotated[bool, Profile.EXPERT] = Field(
        default=False,
        description="Enable verbose FloPy logging for MODFLOW 6 setup and execution.",
    )
    mf6_outer_dvclose: Annotated[PositiveFloat, Profile.EXPERT] = Field(
        default=1e-4,
        description="IMS outer-iteration head-change convergence criterion.",
    )
    mf6_inner_dvclose: Annotated[PositiveFloat, Profile.EXPERT] = Field(
        default=1e-4,
        description="IMS inner-iteration head-change convergence criterion.",
    )
    mf6_outer_maximum: Annotated[PositiveInt, Profile.EXPERT] = Field(
        default=500,
        description="Maximum number of IMS outer iterations.",
    )
    mf6_inner_maximum: Annotated[PositiveInt, Profile.EXPERT] = Field(
        default=500,
        description="Maximum number of IMS inner iterations.",
    )
    mf6_inner_rclose: Annotated[PositiveFloat | None, Profile.EXPERT] = Field(
        default=None,
        description=(
            "IMS inner-iteration flow-residual closure (L^3/T in run units). "
            "None keeps the complexity-preset default."
        ),
    )
    mf6_linear_acceleration: Annotated[Literal["CG", "BICGSTAB"] | None, Profile.EXPERT] = Field(
        default=None,
        description=(
            "IMS linear acceleration: CG for symmetric matrices, BICGSTAB for the "
            "non-symmetric Newton formulation. None keeps the preset default."
        ),
    )
    mf6_under_relaxation: Annotated[
        Literal["NONE", "SIMPLE", "COOLEY", "DBD"] | None, Profile.EXPERT
    ] = Field(
        default=None,
        description=(
            "IMS non-linear under-relaxation scheme. DBD is recommended with Newton. "
            "None keeps the preset default."
        ),
    )
    mf6_enable_rewet: Annotated[bool | None, Profile.EXPERT] = Field(
        default=None,
        description=(
            "Enable NPF cell rewetting. When left to None, HydroModPy "
            "keeps rewetting disabled unless explicitly enabled."
        ),
    )
    mf6_newton: Annotated[bool, Profile.EXPERT] = Field(
        default=True,
        description=(
            "Enable the MODFLOW 6 Newton-Raphson formulation. Catchment cells are "
            "always convertible (unconfined), so Newton with under-relaxation is the "
            "robust default and matches the MODFLOW-NWT backend."
        ),
    )
    mf6_newton_under_relaxation: Annotated[bool, Profile.EXPERT] = Field(
        default=True,
        description=("Enable MODFLOW 6 Newton under-relaxation when mf6_newton is true."),
    )
    mf6_enable_xt3d: Annotated[bool | None, Profile.EXPERT] = Field(
        default=None,
        description=(
            "Enable MF6 NPF XT3D terms. When left to None, HydroModPy "
            "auto-enables XT3D on unstructured solver meshes. This increases "
            "computational cost but can improve accuracy on unstructured or "
            "non-orthogonal grids."
        ),
    )
    mf6_rewet_wetfct: Annotated[PositiveFloat, Profile.EXPERT] = Field(
        default=0.1,
        description="MF6 NPF rewet WETFCT factor.",
    )
    mf6_rewet_iwetit: Annotated[PositiveInt, Profile.EXPERT] = Field(
        default=1,
        description="MF6 NPF rewet IWETIT interval.",
    )
    mf6_rewet_ihdwet: Annotated[int, Profile.EXPERT] = Field(
        default=0,
        description="MF6 NPF rewet IHDWET flag.",
    )
    mf6_rewet_wetdry: Annotated[PositiveFloat, Profile.EXPERT] = Field(
        default=0.1,
        description="MF6 NPF WETDRY threshold used when rewetting is active.",
    )


class Modflow6ProcessSpecificConfig(HydroModelBase):
    """Process-specific parameters used by selected MODFLOW 6 packages."""

    vka: Annotated[PositiveFloat, Profile.EXPERT] = Field(
        default=1.0,
        description="Vertical anisotropy ratio kh/kv (dimensionless, > 0). k33 = k / vka.",
    )
    evt_extinction_depth: Annotated[PositiveFloat, Profile.EXPERT] = Field(
        default=1.0,
        description=(
            "Meters; extinction depth for the EVT sink used when recharge negatives "
            "are routed to EVT. The routed deficit tapers linearly from the cell top "
            "to this depth and stops below it, so a sustained climatic deficit can "
            "saturate near this value."
        ),
    )


class Modflow6Config(HydroModelBase):
    """Expert-level MODFLOW 6 configuration organized by concern."""

    runtime: Annotated[Modflow6RuntimeConfig, Profile.EXPERT] = Field(
        default_factory=Modflow6RuntimeConfig,
        description="MODFLOW 6 runtime options.",
    )
    process_specific: Annotated[Modflow6ProcessSpecificConfig, Profile.EXPERT] = Field(
        default_factory=Modflow6ProcessSpecificConfig,
        description="Process-specific controls for MODFLOW 6 flow packages.",
    )
    sgrid: Annotated[SolverSGridConfig, Profile.USER] = Field(
        default_factory=SolverSGridConfig,
        description="Solver-grid payload split into planar and vertical sections.",
    )
    tgrid: Annotated[TMeshConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional temporal discretization payload as TMeshConfig. In "
            "launcher mode, stress periods are driven by [simulation.time]; "
            "steady/transient policy is driven by [flow].flow_regime and "
            "[flow].first_period_steady."
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
    tgrid: TMeshConfig | None = None

    @classmethod
    def from_config(
        cls,
        config: Modflow6Config | Mapping[str, object] | None = None,
    ) -> Modflow6SpecifParams:
        validated = _coerce_modflow6_config(config)
        return cls(
            runtime=validated.runtime,
            process_specific=validated.process_specific,
            sgrid=validated.sgrid,
            tgrid=validated.tgrid,
        )
