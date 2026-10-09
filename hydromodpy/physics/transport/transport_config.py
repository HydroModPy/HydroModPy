"""Pydantic configuration model for transport-process definitions."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.physics.base import ProcessSpatialConfig


class ModpathParametersConfig(HydroModelBase):
    """Configuration payload for the Modpath transport solver."""

    zone_partic: Annotated[str, Profile.USER] = Field(
        default="domain",
        description=(
            "Where particles are released: 'domain' (every active cell), "
            "'seepage_clip' (the seepage areas of the flow run, clipped to the "
            "watershed), or the path of a raster that marks the release cells."
        ),
    )
    track_dir: Annotated[Literal["forward", "backward"], Profile.USER] = Field(
        default="forward",
        description=(
            "Direction particles are tracked in: with the flow ('forward') or against "
            "it ('backward', from where water leaves back to where it entered)."
        ),
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
    sel_slice: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description=(
            "Keep one released particle out of this many, in release order. Unset, "
            "every particle is kept. A count."
        ),
        json_schema_extra={"unit": "-"},
    )

    @field_validator("track_dir", mode="before")
    @classmethod
    def _refuse_custom_track_dir(cls, value: object) -> object:
        """Refuse 'custom': MODPATH would get no starting location from it."""
        if isinstance(value, str) and value.strip().lower() == "custom":
            raise ValueError(
                "track_dir = 'custom' gives MODPATH no starting location, so no "
                "particle would be released. Write 'forward' or 'backward', and mark "
                "the release cells with zone_partic."
            )
        return value


class TransportModpathConfig(HydroModelBase):
    """Container for Modpath solver settings."""

    parameters: Annotated[ModpathParametersConfig, Profile.USER] = Field(
        default_factory=ModpathParametersConfig,
        description="Solver parameter block used by Modpath.",
    )


class ConcentrationTransportParametersConfig(HydroModelBase):
    """Configuration payload shared by concentration transport solvers."""

    spc_name: Annotated[str, Profile.USER] = Field(
        default="NO3",
        description="Name of the transported solute, used in the output names.",
    )
    sconc_init: Annotated[float, Profile.USER] = Field(
        default=0.0,
        description=(
            "Concentration of the solute in the aquifer at the start of the run, in the "
            "mass per volume unit you choose. The run keeps that unit."
        ),
        json_schema_extra={"unit": "mass/volume"},
    )
    sconc_input: Annotated[float, Profile.USER] = Field(
        default=0.0,
        description=(
            "Concentration of the solute in the recharge water, in the same unit as sconc_init."
        ),
        json_schema_extra={"unit": "mass/volume"},
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
        description=(
            "Molecular diffusion coefficient in m2/s. The MODFLOW 6 GWT backend "
            "runs on the SI SECONDS clock, so this value is consumed per second "
            "(a per-day value is ~86400x too large)."
        ),
    )
    react_order: Annotated[Literal[None, 0, 1], Profile.DEV] = Field(
        default=None,
        description=(
            "Reaction order for MODFLOW 6 GWT and MT3DMS: None (no decay), 0 "
            "(zero-order, constant rate in mass per volume per second), or 1 "
            "(first-order, proportional to concentration, in 1/s). Rates are on "
            "the SI SECONDS clock used by the GWT backend."
        ),
    )
    scheme: Annotated[Literal["upstream", "central", "TVD"], Profile.DEV] = Field(
        default="upstream",
        description=(
            "Advection scheme for MODFLOW 6 GWT. upstream: robust but diffusive "
            "(default). central: least diffusive, may oscillate. TVD: accurate "
            "sharp fronts (Ogata-Banks)."
        ),
    )
    rate_decay: Annotated[float, Profile.DEV] = Field(
        default=0.0,
        description=(
            "Decay rate on the SI SECONDS clock used by the MODFLOW 6 GWT backend: "
            "1/s for first-order (react_order=1), mass per volume per second for "
            "zero-order (react_order=0). A per-day value is ~86400x too large and "
            "annihilates the solute. Can be overridden at runtime."
        ),
    )
    porosity: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        le=1.0,
        json_schema_extra={"unit": "-"},
        description=(
            "Effective (total) porosity [-], the dimensionless volume of interconnected "
            "pores per bulk volume. Drives MST pore volume and pore velocity. When omitted, "
            "the flow model specific yield is used, which underestimates pore volume and "
            "biases transit times low."
        ),
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

    release_zone: Annotated[str, Profile.USER] = Field(
        default="domain",
        description=(
            "Cells particles are released from: 'domain' (every active cell), "
            "'domain_nonriver' (the same without river cells), 'upstream' (the highest "
            "cells), 'upstream_nonriver', 'river', 'outlet' (the lowest cells), or "
            "'custom' (the cells particle_cell_ids lists)."
        ),
    )
    upstream_top_quantile: Annotated[float, Profile.USER] = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description=(
            "Top-elevation quantile used by upstream release zones. A value of 0.90 "
            "selects cells in the highest 10 percent of active cell-top elevations."
        ),
        json_schema_extra={"unit": "-"},
    )
    outlet_bottom_quantile: Annotated[float, Profile.USER] = Field(
        default=0.10,
        ge=0.0,
        le=1.0,
        description=(
            "Bottom-elevation quantile used by the 'outlet' release zone. A value of "
            "0.10 selects cells in the lowest 10 percent of active cell-top elevations."
        ),
        json_schema_extra={"unit": "-"},
    )
    track_dir: Annotated[Literal["forward"], Profile.USER] = Field(
        default="forward",
        description=(
            "Direction particles are tracked in. MODFLOW 6 PRT tracks with the flow "
            "only, so 'forward' is the one value."
        ),
    )
    porosity: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        le=1.0,
        json_schema_extra={"unit": "-"},
        description=(
            "Effective (total) porosity [-] for particle tracking (v = q / porosity). "
            "When omitted, the flow model specific yield is used where positive, with a "
            "warning, since specific yield underestimates pore volume."
        ),
    )
    local_z: Annotated[float, Profile.USER] = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Height of the release point inside its cell, from 0 at the bottom to 1 at the top."
        ),
        json_schema_extra={"unit": "-"},
    )
    particle_cell_ids: Annotated[
        list[int] | None, Profile.USER, VisibleWhen("release_zone", "custom")
    ] = Field(
        default=None,
        description=("Cells to release particles from, by their index in the mesh counted from 0."),
    )
    max_particles: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description=(
            "Most release cells kept after the zone is selected; the kept cells are "
            "spread over the zone. Unset, every cell of the zone releases. A count."
        ),
        json_schema_extra={"unit": "-"},
    )
    sel_slice: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description=(
            "Keep one release cell out of this many, in cell order, before max_particles "
            "applies. A count."
        ),
        json_schema_extra={"unit": "-"},
    )
    release_times_days: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Times particles are released at, in days from the start of the run. Unset, "
            "they are released once at the start."
        ),
        json_schema_extra={"unit": "day"},
    )
    track_times_days: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Times the particle positions are written at, in days from the start of the run."
        ),
        json_schema_extra={"unit": "day"},
    )
    track_time_step_days: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Spacing, in days, of regular output times from 0 to stop_time_days. "
            "track_times_days wins when it is given. It needs stop_time_days."
        ),
        json_schema_extra={"unit": "day"},
    )
    stop_time_days: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description="Time all particles stop at, in days from the start of the run.",
        json_schema_extra={"unit": "day"},
    )
    stop_travel_time_days: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description="Longest time a particle may travel, in days from its release.",
        json_schema_extra={"unit": "day"},
    )
    extend_tracking: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Keep tracking particles after the last flow time step, with the last flow "
            "field, when MODFLOW 6 allows it."
        ),
    )
    dry_tracking_method: Annotated[Literal["drop", "stop", "stay"], Profile.DEV] = Field(
        default="drop",
        description="MF6 PRT behavior for dry-but-active cells.",
    )
    exit_solve_tolerance: Annotated[float, Profile.DEV] = Field(
        default=1.0e-5,
        gt=0.0,
        description=(
            "PRT generalized Pollock exit solve tolerance. Matches the MF6 "
            "prt-prp.dfn default (1e-5), which works well for many problems."
        ),
    )
    write_track_csv: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Write the particle track CSV file. HydroModPy reads the tracks from it, so "
            "turning it off leaves the run with no particle result."
        ),
    )
    write_track_binary: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Write the binary particle track file of MODFLOW 6 as well.",
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
