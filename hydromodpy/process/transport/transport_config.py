"""Pydantic configuration model for transport-process definitions."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from hydromodpy.config.param_level import ParamLevel


class ParticleParametersConfig(BaseModel):
    """Configuration payload for MODPATH particle-tracking inputs."""

    zone_partic: Annotated[str, ParamLevel("advanced")] = Field(
        default="domain",
        description=(
            "Particle injection zone selector: 'domain', 'seepage_clip', or a raster path."
        ),
    )
    track_dir: Annotated[Literal["forward", "backward", "custom"], ParamLevel("advanced")] = Field(
        default="forward",
        description="Particle tracking direction.",
    )
    bore_depth: Annotated[list[float] | None, ParamLevel("advanced")] = Field(
        default=None,
        description="Optional bore depth list used for vertical particle injection.",
    )
    cell_div: Annotated[int, ParamLevel("advanced")] = Field(
        default=1,
        ge=1,
        description="Number of particles per axis in each cell.",
    )
    zloc_div: Annotated[bool, ParamLevel("advanced")] = Field(
        default=False,
        description="If true, apply vertical subdivision for particle injection.",
    )
    sel_random: Annotated[int | None, ParamLevel("advanced")] = Field(
        default=None,
        ge=1,
        description="Optional random downsampling count of injected particles.",
    )
    sel_slice: Annotated[int | None, ParamLevel("advanced")] = Field(
        default=None,
        ge=1,
        description="Optional slicing step for injected particles.",
    )


class TransportParticleConfig(BaseModel):
    """Container for particle-tracking settings."""

    parameters: ParticleParametersConfig = Field(
        default_factory=ParticleParametersConfig,
        description="Particle-tracking parameter block used by Modpath.",
    )


class ConcParametersConfig(BaseModel):
    """Configuration payload for MT3DMS concentration settings."""

    spc_name: Annotated[str, ParamLevel("advanced")] = Field(
        default="NO3",
        description="Name of transported species.",
    )
    sconc_init: Annotated[float, ParamLevel("advanced")] = Field(
        default=0.0,
        description="Initial concentration value (can be overridden at runtime).",
    )
    sconc_input: Annotated[float, ParamLevel("advanced")] = Field(
        default=0.0,
        description="Recharge concentration input value (can be overridden at runtime).",
    )
    disp_long: Annotated[float, ParamLevel("advanced")] = Field(
        default=0.0,
        description="Longitudinal dispersivity [L].",
    )
    disp_transh: Annotated[float, ParamLevel("advanced")] = Field(
        default=0.0,
        description="Horizontal transverse dispersivity ratio.",
    )
    disp_transv: Annotated[float, ParamLevel("advanced")] = Field(
        default=0.0,
        description="Vertical transverse dispersivity ratio.",
    )
    diffu_coeff: Annotated[float, ParamLevel("advanced")] = Field(
        default=0.0,
        description="Molecular diffusion coefficient [L2/T].",
    )
    react_order: Annotated[int | None, ParamLevel("advanced")] = Field(
        default=None,
        description="Reaction order for MT3DMS: None, 0, or 1.",
    )
    rate_decay: Annotated[float, ParamLevel("advanced")] = Field(
        default=0.0,
        description="Decay rate value (can be overridden at runtime).",
    )
    plot_conc: Annotated[bool, ParamLevel("advanced")] = Field(
        default=True,
        description="Enable concentration plotting outputs.",
    )


class TransportConcConfig(BaseModel):
    """Container for MT3DMS concentration settings."""

    parameters: ConcParametersConfig = Field(
        default_factory=ConcParametersConfig,
        description="Concentration/transport parameter block used by Mt3dms.",
    )


class TransportConfig(BaseModel):
    """Transport-process configuration."""

    particle: TransportParticleConfig = Field(
        default_factory=TransportParticleConfig,
        description="Particle-tracking configuration block.",
    )
    conc: TransportConcConfig = Field(
        default_factory=TransportConcConfig,
        description="Concentration transport configuration block.",
    )
