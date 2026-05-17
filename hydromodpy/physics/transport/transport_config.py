"""Pydantic configuration model for transport-process definitions."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.physics.base import ProcessSpatialConfig


class ModpathParametersConfig(HydroModelBase):
    """Configuration payload for the Modpath transport solver."""

    zone_partic: Annotated[str, Profile.DEV] = Field(
        default="domain",
        description=(
            "Particle injection zone selector: 'domain', 'seepage_clip', or a raster path."
        ),
    )
    track_dir: Annotated[Literal["forward", "backward", "custom"], Profile.DEV] = Field(
        default="forward",
        description="Particle tracking direction.",
    )
    bore_depth: Annotated[list[float] | None, Profile.DEV] = Field(
        default=None,
        description="Optional bore depth list used for vertical particle injection.",
    )
    cell_div: Annotated[int, Profile.DEV] = Field(
        default=1,
        ge=1,
        description="Number of particles per axis in each cell.",
    )
    zloc_div: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="If true, apply vertical subdivision for particle injection.",
    )
    sel_random: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        ge=1,
        description="Optional random downsampling count of injected particles.",
    )
    sel_slice: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        ge=1,
        description="Optional slicing step for injected particles.",
    )


class TransportModpathConfig(HydroModelBase):
    """Container for Modpath solver settings."""

    parameters: Annotated[ModpathParametersConfig, Profile.USER] = Field(
        default_factory=ModpathParametersConfig,
        description="Solver parameter block used by Modpath.",
    )


class ConcentrationTransportParametersConfig(HydroModelBase):
    """Configuration payload shared by concentration transport solvers."""

    spc_name: Annotated[str, Profile.DEV] = Field(
        default="NO3",
        description="Name of transported species.",
    )
    sconc_init: Annotated[float, Profile.DEV] = Field(
        default=0.0,
        description="Initial concentration value (can be overridden at runtime).",
    )
    sconc_input: Annotated[float, Profile.DEV] = Field(
        default=0.0,
        description="Recharge concentration input value (can be overridden at runtime).",
    )
    disp_long: Annotated[float, Profile.DEV] = Field(
        default=0.0,
        description="Longitudinal dispersivity [L].",
    )
    disp_transh: Annotated[float, Profile.DEV] = Field(
        default=0.0,
        description="Horizontal transverse dispersivity ratio.",
    )
    disp_transv: Annotated[float, Profile.DEV] = Field(
        default=0.0,
        description="Vertical transverse dispersivity ratio.",
    )
    diffu_coeff: Annotated[float, Profile.DEV] = Field(
        default=0.0,
        description="Molecular diffusion coefficient [L2/T].",
    )
    react_order: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        description="Reaction order for MT3DMS: None, 0, or 1.",
    )
    rate_decay: Annotated[float, Profile.DEV] = Field(
        default=0.0,
        description="Decay rate value (can be overridden at runtime).",
    )
    plot_conc: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Enable concentration plotting outputs.",
    )


class TransportMt3dmsConfig(HydroModelBase):
    """Container for MT3DMS solver settings."""

    parameters: Annotated[ConcentrationTransportParametersConfig, Profile.USER] = Field(
        default_factory=ConcentrationTransportParametersConfig,
        description="Solver parameter block used by Mt3dms.",
    )


class TransportModflow6GwtConfig(HydroModelBase):
    """Container for MODFLOW 6 GWT solver settings."""

    parameters: Annotated[ConcentrationTransportParametersConfig, Profile.USER] = Field(
        default_factory=ConcentrationTransportParametersConfig,
        description="Solver parameter block used by Modflow6Transport.",
    )


class Modflow6PrtParametersConfig(HydroModelBase):
    """Configuration payload for MODFLOW 6 PRT particle tracking."""

    release_zone: Annotated[str, Profile.DEV] = Field(
        default="domain",
        description=(
            "Particle release selector: 'domain', 'upstream', 'upstream_nonriver', "
            "'river', 'outlet', or 'custom'."
        ),
    )
    upstream_top_quantile: Annotated[float, Profile.DEV] = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description=(
            "Top-elevation quantile used by upstream release zones. A value of 0.90 "
            "selects cells in the highest 10 percent of active cell-top elevations."
        ),
    )
    track_dir: Annotated[Literal["forward"], Profile.DEV] = Field(
        default="forward",
        description="Particle tracking direction. MF6 PRT support is currently forward only.",
    )
    porosity: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        gt=0.0,
        description=(
            "Optional uniform particle-tracking porosity. When omitted, the "
            "flow model specific yield is used where positive."
        ),
    )
    local_z: Annotated[float, Profile.DEV] = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Local vertical release coordinate within the cell.",
    )
    particle_cell_ids: Annotated[list[int] | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional zero-based DISV cell2d ids for explicit particle release. "
            "Used when release_zone is 'custom'."
        ),
    )
    max_particles: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        ge=1,
        description="Optional maximum number of release cells after zone selection.",
    )
    sel_slice: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        ge=1,
        description="Optional deterministic slicing step for selected release cells.",
    )
    release_times_days: Annotated[list[float] | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional particle release times in model time units. Existing "
            "MODFLOW 6 models in HydroModPy use days."
        ),
    )
    track_times_days: Annotated[list[float] | None, Profile.DEV] = Field(
        default=None,
        description="Optional user tracking output times in model time units.",
    )
    track_time_step_days: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        gt=0.0,
        description=(
            "Optional regular spacing, in days, for generated PRT tracking output times. "
            "Used only when track_times_days is omitted."
        ),
    )
    stop_time_days: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        gt=0.0,
        description="Optional absolute particle stop time in model time units.",
    )
    stop_travel_time_days: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        gt=0.0,
        description="Optional maximum particle travel time in model time units.",
    )
    extend_tracking: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Track particles beyond the final flow time step when MF6 permits it.",
    )
    dry_tracking_method: Annotated[Literal["drop", "stop", "stay"], Profile.DEV] = Field(
        default="drop",
        description="MF6 PRT behavior for dry-but-active cells.",
    )
    exit_solve_tolerance: Annotated[float, Profile.DEV] = Field(
        default=1.0e-10,
        gt=0.0,
        description="PRT generalized Pollock exit solve tolerance.",
    )
    write_track_csv: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Write the PRT track CSV file used by the HydroModPy extractor.",
    )
    write_track_binary: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Write the binary PRT track file.",
    )


class TransportModflow6PrtConfig(HydroModelBase):
    """Container for MODFLOW 6 PRT particle-tracking settings."""

    parameters: Annotated[Modflow6PrtParametersConfig, Profile.USER] = Field(
        default_factory=Modflow6PrtParametersConfig,
        description="Solver parameter block used by Modflow6Prt.",
    )


class TransportConfig(ProcessSpatialConfig):
    """Transport-process configuration."""

    # Keep shared ProcessSpatial schema inheritance, but exclude these generic
    # containers from default transport serialization.
    param_list: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        exclude=True,
        description="Inherited generic parameter list (excluded from transport serialization).",
    )
    param: Annotated[dict[str, object], Profile.USER] = Field(
        default_factory=dict,
        exclude=True,
        description="Inherited generic parameter map (excluded from transport serialization).",
    )
    ic: Annotated[object | None, Profile.USER] = Field(
        default=None,
        exclude=True,
        description="Inherited initial-condition payload (excluded from transport serialization).",
    )
    bc: Annotated[dict[str, object], Profile.USER] = Field(
        default_factory=dict,
        exclude=True,
        description="Inherited boundary-condition map (excluded from transport serialization).",
    )
    sinks_sources: Annotated[dict[str, object], Profile.USER] = Field(
        default_factory=dict,
        exclude=True,
        description="Inherited sinks/sources map (excluded from transport serialization).",
    )

    modpath: Annotated[TransportModpathConfig, Profile.USER] = Field(
        default_factory=TransportModpathConfig,
        description="Modpath solver configuration block.",
    )
    mt3dms: Annotated[TransportMt3dmsConfig, Profile.USER] = Field(
        default_factory=TransportMt3dmsConfig,
        description="MT3DMS solver configuration block.",
    )
    modflow6gwt: Annotated[TransportModflow6GwtConfig, Profile.USER] = Field(
        default_factory=TransportModflow6GwtConfig,
        description="MODFLOW 6 GWT solver configuration block.",
    )
    modflow6prt: Annotated[TransportModflow6PrtConfig, Profile.USER] = Field(
        default_factory=TransportModflow6PrtConfig,
        description="MODFLOW 6 PRT particle-tracking solver configuration block.",
    )
