"""Pydantic configuration model for transport-process definitions."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.process.prototype import ProcessSpatialConfig


class ModpathParametersConfig(BaseModel):
    """Configuration payload for the Modpath transport solver."""

    model_config = ConfigDict(extra="forbid")

    zone_partic: Annotated[str, ParamLevel("dev")] = Field(
        default="domain",
        description=(
            "Particle injection zone selector: 'domain', 'seepage_clip', or a raster path."
        ),
    )
    track_dir: Annotated[Literal["forward", "backward", "custom"], ParamLevel("dev")] = Field(
        default="forward",
        description="Particle tracking direction.",
    )
    bore_depth: Annotated[list[float] | None, ParamLevel("dev")] = Field(
        default=None,
        description="Optional bore depth list used for vertical particle injection.",
    )
    cell_div: Annotated[int, ParamLevel("dev")] = Field(
        default=1,
        ge=1,
        description="Number of particles per axis in each cell.",
    )
    zloc_div: Annotated[bool, ParamLevel("dev")] = Field(
        default=False,
        description="If true, apply vertical subdivision for particle injection.",
    )
    sel_random: Annotated[int | None, ParamLevel("dev")] = Field(
        default=None,
        ge=1,
        description="Optional random downsampling count of injected particles.",
    )
    sel_slice: Annotated[int | None, ParamLevel("dev")] = Field(
        default=None,
        ge=1,
        description="Optional slicing step for injected particles.",
    )


class TransportModpathConfig(BaseModel):
    """Container for Modpath solver settings."""

    model_config = ConfigDict(extra="forbid")

    parameters: ModpathParametersConfig = Field(
        default_factory=ModpathParametersConfig,
        description="Solver parameter block used by Modpath.",
    )


class ConcentrationTransportParametersConfig(BaseModel):
    """Configuration payload shared by concentration transport solvers."""

    model_config = ConfigDict(extra="forbid")

    spc_name: Annotated[str, ParamLevel("dev")] = Field(
        default="NO3",
        description="Name of transported species.",
    )
    sconc_init: Annotated[float, ParamLevel("dev")] = Field(
        default=0.0,
        description="Initial concentration value (can be overridden at runtime).",
    )
    sconc_input: Annotated[float, ParamLevel("dev")] = Field(
        default=0.0,
        description="Recharge concentration input value (can be overridden at runtime).",
    )
    disp_long: Annotated[float, ParamLevel("dev")] = Field(
        default=0.0,
        description="Longitudinal dispersivity [L].",
    )
    disp_transh: Annotated[float, ParamLevel("dev")] = Field(
        default=0.0,
        description="Horizontal transverse dispersivity ratio.",
    )
    disp_transv: Annotated[float, ParamLevel("dev")] = Field(
        default=0.0,
        description="Vertical transverse dispersivity ratio.",
    )
    diffu_coeff: Annotated[float, ParamLevel("dev")] = Field(
        default=0.0,
        description="Molecular diffusion coefficient [L2/T].",
    )
    react_order: Annotated[int | None, ParamLevel("dev")] = Field(
        default=None,
        description="Reaction order for MT3DMS: None, 0, or 1.",
    )
    rate_decay: Annotated[float, ParamLevel("dev")] = Field(
        default=0.0,
        description="Decay rate value (can be overridden at runtime).",
    )
    plot_conc: Annotated[bool, ParamLevel("dev")] = Field(
        default=True,
        description="Enable concentration plotting outputs.",
    )


class TransportMt3dmsConfig(BaseModel):
    """Container for MT3DMS solver settings."""

    model_config = ConfigDict(extra="forbid")

    parameters: ConcentrationTransportParametersConfig = Field(
        default_factory=ConcentrationTransportParametersConfig,
        description="Solver parameter block used by Mt3dms.",
    )


class TransportModflow6GwtConfig(BaseModel):
    """Container for MODFLOW 6 GWT solver settings."""

    model_config = ConfigDict(extra="forbid")

    parameters: ConcentrationTransportParametersConfig = Field(
        default_factory=ConcentrationTransportParametersConfig,
        description="Solver parameter block used by Modflow6Transport.",
    )


class TransportConfig(ProcessSpatialConfig):
    """Transport-process configuration."""

    # Keep shared ProcessSpatial schema inheritance, but keep these generic
    # containers out of default transport serialization for backward compatibility.
    param_list: list[str] = Field(default_factory=list, exclude=True)
    param: dict[str, object] = Field(default_factory=dict, exclude=True)
    ic: object | None = Field(default=None, exclude=True)
    bc: dict[str, object] = Field(default_factory=dict, exclude=True)
    sinks_sources: dict[str, object] = Field(default_factory=dict, exclude=True)

    modpath: TransportModpathConfig = Field(
        default_factory=TransportModpathConfig,
        description="Modpath solver configuration block.",
    )
    mt3dms: TransportMt3dmsConfig = Field(
        default_factory=TransportMt3dmsConfig,
        description="MT3DMS solver configuration block.",
    )
    modflow6gwt: TransportModflow6GwtConfig = Field(
        default_factory=TransportModflow6GwtConfig,
        description="MODFLOW 6 GWT solver configuration block.",
    )
