"""Pydantic and runtime configuration for MODFLOW-NWT expert parameters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated

from pydantic import ConfigDict, Field, field_validator

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.profile import Profile
from hydromodpy.core.units.length import parse_length_to_m
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_config import SolverSGridConfig
from hydromodpy.solver.utils.temporal.tmesh_config import TMeshConfig


class ModflowRuntimeConfig(HydroModelBase):
    """Expert runtime settings used to build and solve MODFLOW-NWT packages."""

    model_config = ConfigDict(extra="forbid")

    mf_version: Annotated[str, Profile.EXPERT] = Field(
        default="mfnwt",
        description="MODFLOW executable/version identifier passed to FloPy.",
    )
    mf_listunit: Annotated[int, Profile.EXPERT] = Field(
        default=2,
        description="Fortran unit number used for the MODFLOW list file.",
    )
    mf_verbose: Annotated[bool, Profile.EXPERT] = Field(
        default=False,
        description="Enable verbose FloPy logging for model setup.",
    )

    nwt_headtol: Annotated[float, Profile.EXPERT] = Field(
        default=1e-4,
        description="Head closure criterion for the NWT nonlinear solver.",
    )
    nwt_fluxtol: Annotated[float, Profile.EXPERT] = Field(
        default=500.0,
        description="Flux closure criterion for the NWT nonlinear solver.",
    )
    nwt_maxiterout: Annotated[int, Profile.EXPERT] = Field(
        default=5000,
        description="Maximum outer nonlinear iterations in the NWT solver.",
    )
    nwt_thickfact: Annotated[float, Profile.EXPERT] = Field(
        default=1e-5,
        description="NWT wetting/thickness factor controlling nonlinear updates.",
    )
    nwt_linmeth: Annotated[int, Profile.EXPERT] = Field(
        default=1,
        description="Linear solver choice for NWT (see MODFLOW-NWT documentation).",
    )
    nwt_iprnwt: Annotated[int, Profile.EXPERT] = Field(
        default=1,
        description="NWT print flag controlling iteration diagnostics in listing outputs.",
    )
    nwt_ibotav: Annotated[int, Profile.EXPERT] = Field(
        default=1,
        description="NWT option for averaging saturated thickness at the cell bottom.",
    )
    nwt_options: Annotated[str, Profile.EXPERT] = Field(
        default="COMPLEX",
        description="NWT nonlinear option keyword (for example SIMPLE or COMPLEX).",
    )
    nwt_continue: Annotated[bool, Profile.EXPERT] = Field(
        default=False,
        description="If true, continue NWT iterations on partially converged stress periods.",
    )
    nwt_backflag: Annotated[int, Profile.EXPERT] = Field(
        default=0,
        description="NWT backtracking activation flag.",
    )
    nwt_stoptol: Annotated[float, Profile.EXPERT] = Field(
        default=1e-10,
        description="NWT backtracking stopping tolerance.",
    )

    dis_itmuni: Annotated[int, Profile.EXPERT] = Field(
        default=0,
        description="DIS time unit code used by MODFLOW (ITMUNI).",
    )

    bas_hnoflo: Annotated[float, Profile.EXPERT] = Field(
        default=-9999.0,
        description="BAS no-flow head sentinel value (HNOFLO).",
    )

    upw_iphdry: Annotated[int, Profile.EXPERT] = Field(
        default=1,
        description="UPW dry-cell head output flag (IPHDRY).",
    )
    upw_hdry: Annotated[float, Profile.EXPERT] = Field(
        default=-100.0,
        description="UPW dry-cell head value (HDRY).",
    )
    upw_layvka: Annotated[int, Profile.EXPERT] = Field(
        default=1,
        description="UPW flag controlling VKA interpretation per layer (LAYVKA).",
    )

    evt_nevtop: Annotated[int, Profile.EXPERT] = Field(
        default=3,
        description="EVT option code that defines how ET extinction depth is applied (NEVTOP).",
    )
    evt_ievt: Annotated[int, Profile.EXPERT] = Field(
        default=1,
        description="EVT integer array selector used when NEVTOP requires layer indices (IEVT).",
    )
    evt_ipakcb: Annotated[int, Profile.EXPERT] = Field(
        default=1,
        description="EVT cell-by-cell budget output flag (IPAKCB).",
    )

    oc_compact: Annotated[bool, Profile.EXPERT] = Field(
        default=True,
        description="Enable compact budget format in OC outputs.",
    )

    wel_ipakcb: Annotated[int, Profile.EXPERT] = Field(
        default=1,
        description="WEL cell-by-cell budget output flag (IPAKCB).",
    )

    lmt_output_file_name: Annotated[str, Profile.EXPERT] = Field(
        default="mt3d_link.ftl",
        description="LMT output filename used to couple MODFLOW to MT3DMS.",
    )
    lmt_extension: Annotated[str, Profile.EXPERT] = Field(
        default="lmt8",
        description="LMT package filename extension.",
    )
    lmt_output_format: Annotated[str, Profile.EXPERT] = Field(
        default="unformatted",
        description="LMT file format (typically 'formatted' or 'unformatted').",
    )


class ModflowProcessSpecificConfig(HydroModelBase):
    """Process-specific parameters used by selected MODFLOW packages."""

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

    runtime: Annotated[ModflowRuntimeConfig, Profile.EXPERT] = Field(
        default_factory=ModflowRuntimeConfig,
        description="MODFLOW runtime package options (NWT/DIS/BAS/UPW/EVT/OC/WEL/LMT).",
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
