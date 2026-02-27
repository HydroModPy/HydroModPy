"""Pydantic and runtime configuration for MODFLOW-NWT expert parameters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hydromodpy.config.param_level import ParamLevel
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_config import VerticalGridConfig


class ModflowRuntimeConfig(BaseModel):
    """Expert runtime settings used to build and solve MODFLOW-NWT packages."""

    model_config = ConfigDict(extra="forbid")

    mf_version: Annotated[str, ParamLevel("expert")] = Field(
        default="mfnwt",
        description="MODFLOW executable/version identifier passed to FloPy.",
    )
    mf_listunit: Annotated[int, ParamLevel("expert")] = Field(
        default=2,
        description="Fortran unit number used for the MODFLOW list file.",
    )
    mf_verbose: Annotated[bool, ParamLevel("expert")] = Field(
        default=False,
        description="Enable verbose FloPy logging for model setup.",
    )

    nwt_headtol: Annotated[float, ParamLevel("expert")] = Field(
        default=1e-4,
        description="Head closure criterion for the NWT nonlinear solver.",
    )
    nwt_fluxtol: Annotated[float, ParamLevel("expert")] = Field(
        default=500.0,
        description="Flux closure criterion for the NWT nonlinear solver.",
    )
    nwt_maxiterout: Annotated[int, ParamLevel("expert")] = Field(
        default=5000,
        description="Maximum outer nonlinear iterations in the NWT solver.",
    )
    nwt_thickfact: Annotated[float, ParamLevel("expert")] = Field(
        default=1e-5,
        description="NWT wetting/thickness factor controlling nonlinear updates.",
    )
    nwt_linmeth: Annotated[int, ParamLevel("expert")] = Field(
        default=1,
        description="Linear solver choice for NWT (see MODFLOW-NWT documentation).",
    )
    nwt_iprnwt: Annotated[int, ParamLevel("expert")] = Field(
        default=1,
        description="NWT print flag controlling iteration diagnostics in listing outputs.",
    )
    nwt_ibotav: Annotated[int, ParamLevel("expert")] = Field(
        default=1,
        description="NWT option for averaging saturated thickness at the cell bottom.",
    )
    nwt_options: Annotated[str, ParamLevel("expert")] = Field(
        default="COMPLEX",
        description="NWT nonlinear option keyword (for example SIMPLE or COMPLEX).",
    )
    nwt_continue: Annotated[bool, ParamLevel("expert")] = Field(
        default=False,
        description="If true, continue NWT iterations on partially converged stress periods.",
    )
    nwt_backflag: Annotated[int, ParamLevel("expert")] = Field(
        default=0,
        description="NWT backtracking activation flag.",
    )
    nwt_stoptol: Annotated[float, ParamLevel("expert")] = Field(
        default=1e-10,
        description="NWT backtracking stopping tolerance.",
    )

    dis_itmuni: Annotated[int, ParamLevel("expert")] = Field(
        default=0,
        description="DIS time unit code used by MODFLOW (ITMUNI).",
    )

    bas_hnoflo: Annotated[float, ParamLevel("expert")] = Field(
        default=-9999.0,
        description="BAS no-flow head sentinel value (HNOFLO).",
    )

    upw_iphdry: Annotated[int, ParamLevel("expert")] = Field(
        default=1,
        description="UPW dry-cell head output flag (IPHDRY).",
    )
    upw_hdry: Annotated[float, ParamLevel("expert")] = Field(
        default=-100.0,
        description="UPW dry-cell head value (HDRY).",
    )
    upw_layvka: Annotated[int, ParamLevel("expert")] = Field(
        default=1,
        description="UPW flag controlling VKA interpretation per layer (LAYVKA).",
    )

    evt_nevtop: Annotated[int, ParamLevel("expert")] = Field(
        default=3,
        description="EVT option code that defines how ET extinction depth is applied (NEVTOP).",
    )
    evt_ievt: Annotated[int, ParamLevel("expert")] = Field(
        default=1,
        description="EVT integer array selector used when NEVTOP requires layer indices (IEVT).",
    )
    evt_ipakcb: Annotated[int, ParamLevel("expert")] = Field(
        default=1,
        description="EVT cell-by-cell budget output flag (IPAKCB).",
    )

    oc_compact: Annotated[bool, ParamLevel("expert")] = Field(
        default=True,
        description="Enable compact budget format in OC outputs.",
    )

    wel_ipakcb: Annotated[int, ParamLevel("expert")] = Field(
        default=1,
        description="WEL cell-by-cell budget output flag (IPAKCB).",
    )

    lmt_output_file_name: Annotated[str, ParamLevel("expert")] = Field(
        default="mt3d_link.ftl",
        description="LMT output filename used to couple MODFLOW to MT3DMS.",
    )
    lmt_extension: Annotated[str, ParamLevel("expert")] = Field(
        default="lmt8",
        description="LMT package filename extension.",
    )
    lmt_output_format: Annotated[str, ParamLevel("expert")] = Field(
        default="unformatted",
        description="LMT file format (typically 'formatted' or 'unformatted').",
    )


class ModflowProcessSpecificConfig(BaseModel):
    """Process-specific parameters used by selected MODFLOW packages."""

    model_config = ConfigDict(extra="forbid")

    vka: Annotated[float, ParamLevel("expert")] = Field(
        default=1.0,
        description="Vertical hydraulic conductivity control passed to the UPW package (VKA).",
    )
    exdp: Annotated[float, ParamLevel("expert")] = Field(
        default=1.0,
        description="Extinction depth [L] used by the EVT package (EXDP).",
    )


class ModflowConfig(BaseModel):
    """Expert-level MODFLOW configuration organized by concern."""

    model_config = ConfigDict(extra="forbid")

    runtime: Annotated[ModflowRuntimeConfig, ParamLevel("expert")] = Field(
        default_factory=ModflowRuntimeConfig,
        description="MODFLOW runtime package options (NWT/DIS/BAS/UPW/EVT/OC/WEL/LMT).",
    )
    process_specific: Annotated[ModflowProcessSpecificConfig, ParamLevel("expert")] = Field(
        default_factory=ModflowProcessSpecificConfig,
        description="Process-specific package controls (currently UPW/EVT knobs).",
    )
    sgrid: Annotated[dict[str, object] | None, ParamLevel("user")] = Field(
        default=None,
        description=(
            "Optional VerticalGridConfig-keyed overrides for structured-grid "
            "vertical discretization (`genmtd_lay`, `nlay`, `lay_decay`, "
            "`lay_proportions`, `nodata`, `lenuni`)."
        ),
    )

    @field_validator("sgrid")
    @classmethod
    def _validate_sgrid_override_keys(cls, value):
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError("modflow.sgrid must be a mapping of overrides")
        payload = dict(value)
        allowed = set(VerticalGridConfig.model_fields)
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(
                f"Unknown modflow.sgrid key(s): {', '.join(unknown)}. "
                f"Allowed keys are: {', '.join(sorted(allowed))}"
            )
        return payload

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
class ModflowRuntimeParams:
    """Runtime container for MODFLOW-NWT package settings."""

    # Core MODFLOW object
    mf_version: str = "mfnwt"
    mf_listunit: int = 2
    mf_verbose: bool = False

    # NWT solver
    nwt_headtol: float = 1e-4
    nwt_fluxtol: float = 500.0
    nwt_maxiterout: int = 5000
    nwt_thickfact: float = 1e-5
    nwt_linmeth: int = 1
    nwt_iprnwt: int = 1
    nwt_ibotav: int = 1
    nwt_options: str = "COMPLEX"
    nwt_continue: bool = False
    nwt_backflag: int = 0
    nwt_stoptol: float = 1e-10

    # DIS
    dis_itmuni: int = 0

    # BAS
    bas_hnoflo: float = -9999.0

    # UPW
    upw_iphdry: int = 1
    upw_hdry: float = -100.0
    upw_layvka: int = 1

    # EVT
    evt_nevtop: int = 3
    evt_ievt: int = 1
    evt_ipakcb: int = 1

    # OC
    oc_compact: bool = True

    # WEL
    wel_ipakcb: int = 1

    # LMT (MT3DMS coupling)
    lmt_output_file_name: str = "mt3d_link.ftl"
    lmt_extension: str = "lmt8"
    lmt_output_format: str = "unformatted"


@dataclass(frozen=True)
class ModflowProcessSpecificParams:
    """Runtime container for process-specific package settings."""

    vka: float = 1.0
    exdp: float = 1.0


@dataclass(frozen=True)
class ModflowSpecifParams:
    """Runtime container grouped by configuration section."""

    runtime: ModflowRuntimeParams = ModflowRuntimeParams()
    process_specific: ModflowProcessSpecificParams = ModflowProcessSpecificParams()
    sgrid: dict[str, object] | None = None

    @classmethod
    def from_config(
        cls,
        config: ModflowConfig | Mapping[str, object] | None = None,
    ) -> "ModflowSpecifParams":
        """Build runtime params from validated Pydantic config or raw mapping."""
        validated = _coerce_modflow_config(config)
        return cls(
            runtime=ModflowRuntimeParams(**validated.runtime.model_dump()),
            process_specific=ModflowProcessSpecificParams(
                **validated.process_specific.model_dump()
            ),
            sgrid=(dict(validated.sgrid) if validated.sgrid is not None else None),
        )
