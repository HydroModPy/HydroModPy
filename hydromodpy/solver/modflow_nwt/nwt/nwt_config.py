"""Pydantic and runtime configuration for MODFLOW-NWT expert parameters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units.length import parse_length_to_m
from hydromodpy.solver.utils.temporal.tmesh_config import TMeshConfig
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_config import SolverSGridConfig


class NwtSolverConfig(HydroModelBase):
    """MODFLOW-NWT solver package settings."""

    version: Annotated[str, Profile.EXPERT] = Field(
        default="mfnwt",
        description="MODFLOW executable/version identifier passed to FloPy.",
    )
    listunit: Annotated[int, Profile.EXPERT] = Field(
        default=2,
        description="Fortran unit number used for the MODFLOW list file.",
    )
    verbose: Annotated[bool, Profile.EXPERT] = Field(
        default=False,
        description="Enable verbose FloPy logging for model setup.",
    )
    headtol: Annotated[float, Profile.EXPERT] = Field(
        default=1e-4,
        description="Head closure criterion for the NWT nonlinear solver.",
    )
    fluxtol: Annotated[float, Profile.EXPERT] = Field(
        default=500.0,
        description="Flux closure criterion for the NWT nonlinear solver.",
    )
    maxiterout: Annotated[int, Profile.EXPERT] = Field(
        default=5000,
        description="Maximum outer nonlinear iterations in the NWT solver.",
    )
    thickfact: Annotated[float, Profile.EXPERT] = Field(
        default=1e-5,
        description="NWT wetting/thickness factor controlling nonlinear updates.",
    )
    linmeth: Annotated[int, Profile.EXPERT] = Field(
        default=1,
        description="Linear solver choice for NWT (see MODFLOW-NWT documentation).",
    )
    iprnwt: Annotated[int, Profile.EXPERT] = Field(
        default=1,
        description="NWT print flag controlling iteration diagnostics in listing outputs.",
    )
    ibotav: Annotated[int, Profile.EXPERT] = Field(
        default=1,
        description="NWT option for averaging saturated thickness at the cell bottom.",
    )
    options: Annotated[str, Profile.EXPERT] = Field(
        default="COMPLEX",
        description="NWT nonlinear option keyword (for example SIMPLE or COMPLEX).",
    )
    continue_run: Annotated[bool, Profile.EXPERT] = Field(
        default=False,
        description="If true, continue NWT iterations on partially converged stress periods.",
    )
    backflag: Annotated[int, Profile.EXPERT] = Field(
        default=0,
        description="NWT backtracking activation flag.",
    )
    stoptol: Annotated[float, Profile.EXPERT] = Field(
        default=1e-10,
        description="NWT backtracking stopping tolerance.",
    )


class DisConfig(HydroModelBase):
    """DIS package settings."""

    itmuni: Annotated[int, Profile.EXPERT] = Field(
        default=0,
        description="DIS time unit code used by MODFLOW (ITMUNI).",
    )


class BasConfig(HydroModelBase):
    """BAS package settings."""

    hnoflo: Annotated[float, Profile.EXPERT] = Field(
        default=-9999.0,
        description="BAS no-flow head sentinel value (HNOFLO).",
    )


class UpwConfig(HydroModelBase):
    """UPW package settings."""

    iphdry: Annotated[int, Profile.EXPERT] = Field(
        default=1,
        description="UPW dry-cell head output flag (IPHDRY).",
    )
    hdry: Annotated[float, Profile.EXPERT] = Field(
        default=-100.0,
        description="UPW dry-cell head value (HDRY).",
    )
    layvka: Annotated[int, Profile.EXPERT] = Field(
        default=1,
        description="UPW flag controlling VKA interpretation per layer (LAYVKA).",
    )


class EvtConfig(HydroModelBase):
    """EVT package settings."""

    nevtop: Annotated[int, Profile.EXPERT] = Field(
        default=3,
        description="EVT option code that defines how ET extinction depth is applied (NEVTOP).",
    )
    ievt: Annotated[int, Profile.EXPERT] = Field(
        default=1,
        description="EVT integer array selector used when NEVTOP requires layer indices (IEVT).",
    )
    ipakcb: Annotated[int, Profile.EXPERT] = Field(
        default=1,
        description="EVT cell-by-cell budget output flag (IPAKCB).",
    )


class OcConfig(HydroModelBase):
    """OC package settings."""

    compact: Annotated[bool, Profile.EXPERT] = Field(
        default=True,
        description="Enable compact budget format in OC outputs.",
    )


class WelConfig(HydroModelBase):
    """WEL package settings."""

    ipakcb: Annotated[int, Profile.EXPERT] = Field(
        default=1,
        description="WEL cell-by-cell budget output flag (IPAKCB).",
    )


class LmtConfig(HydroModelBase):
    """LMT package settings."""

    output_file_name: Annotated[str, Profile.EXPERT] = Field(
        default="mt3d_link.ftl",
        description="LMT output filename used to couple MODFLOW to MT3DMS.",
    )
    extension: Annotated[str, Profile.EXPERT] = Field(
        default="lmt8",
        description="LMT package filename extension.",
    )
    output_format: Annotated[str, Profile.EXPERT] = Field(
        default="unformatted",
        description="LMT file format (typically 'formatted' or 'unformatted').",
    )


class ModflowRuntimeConfig(HydroModelBase):
    """Expert runtime settings grouped by MODFLOW-NWT package."""

    nwt: Annotated[NwtSolverConfig, Profile.EXPERT] = Field(
        default_factory=NwtSolverConfig,
        description="NWT solver and executable settings.",
    )
    dis: Annotated[DisConfig, Profile.EXPERT] = Field(
        default_factory=DisConfig,
        description="DIS package settings.",
    )
    bas: Annotated[BasConfig, Profile.EXPERT] = Field(
        default_factory=BasConfig,
        description="BAS package settings.",
    )
    upw: Annotated[UpwConfig, Profile.EXPERT] = Field(
        default_factory=UpwConfig,
        description="UPW package settings.",
    )
    evt: Annotated[EvtConfig, Profile.EXPERT] = Field(
        default_factory=EvtConfig,
        description="EVT package settings.",
    )
    oc: Annotated[OcConfig, Profile.EXPERT] = Field(
        default_factory=OcConfig,
        description="OC package settings.",
    )
    wel: Annotated[WelConfig, Profile.EXPERT] = Field(
        default_factory=WelConfig,
        description="WEL package settings.",
    )
    lmt: Annotated[LmtConfig, Profile.EXPERT] = Field(
        default_factory=LmtConfig,
        description="LMT package settings.",
    )


class ModflowProcessSpecificConfig(HydroModelBase):
    """Process-specific parameters used by selected MODFLOW packages."""

    vka: Annotated[float, Profile.EXPERT] = Field(
        default=1.0,
        description="Vertical hydraulic conductivity control passed to the UPW package (VKA).",
    )
    exdp: Annotated[float, Profile.EXPERT] = Field(
        default=1.0,
        description="Extinction depth [L] used by the EVT package (EXDP).",
    )

    @field_validator("exdp", mode="before")
    @classmethod
    def _normalize_exdp(cls, value):
        if value is None:
            return None
        exdp_m = float(
            parse_length_to_m(value, default_unit="m", label="modflownwt.process_specific.exdp")
        )
        if exdp_m <= 0.0:
            raise ValueError("modflownwt.process_specific.exdp must be > 0.")
        return exdp_m


class ModflowConfig(HydroModelBase):
    """Expert-level MODFLOW configuration organized by concern."""

    runtime: Annotated[ModflowRuntimeConfig, Profile.EXPERT] = Field(
        default_factory=ModflowRuntimeConfig,
        description="MODFLOW runtime package options grouped by package.",
    )
    process_specific: Annotated[ModflowProcessSpecificConfig, Profile.EXPERT] = Field(
        default_factory=ModflowProcessSpecificConfig,
        description="Process-specific package controls (currently UPW/EVT knobs).",
    )
    sgrid: Annotated[SolverSGridConfig, Profile.USER] = Field(
        default_factory=SolverSGridConfig,
        description=(
            "Spatial-grid payload split into `[...sgrid.planar]` and `[...sgrid.vertical]`."
        ),
    )
    tgrid: Annotated[TMeshConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional temporal discretization payload as one validated "
            "`TMeshConfig` model. In launcher mode, stress periods are "
            "driven by [simulation.time]; this section is mirrored for "
            "compatibility and mainly keeps `firstpersteady`."
        ),
    )


def _coerce_modflow_config(
    config: ModflowConfig | Mapping[str, object] | None = None,
) -> ModflowConfig:
    if config is None:
        return ModflowConfig()
    if isinstance(config, ModflowConfig):
        return config
    if isinstance(config, Mapping):
        return ModflowConfig.model_validate(dict(config))
    raise TypeError("modflow_config must be None, ModflowConfig, or a mapping of values")


@dataclass(frozen=True)
class ModflowSpecifParams:
    """Runtime container grouped by configuration section.

    Uses the validated Pydantic models directly instead of duplicating fields
    into separate frozen dataclasses.
    """

    runtime: ModflowRuntimeConfig = field(default_factory=ModflowRuntimeConfig)
    process_specific: ModflowProcessSpecificConfig = field(
        default_factory=ModflowProcessSpecificConfig,
    )
    sgrid: SolverSGridConfig = field(default_factory=SolverSGridConfig)
    tgrid: TMeshConfig | None = None

    @classmethod
    def from_config(
        cls,
        config: ModflowConfig | Mapping[str, object] | None = None,
    ) -> ModflowSpecifParams:
        """Build runtime params from validated Pydantic config or raw mapping."""
        validated = _coerce_modflow_config(config)
        return cls(
            runtime=validated.runtime,
            process_specific=validated.process_specific,
            sgrid=validated.sgrid,
            tgrid=validated.tgrid,
        )
