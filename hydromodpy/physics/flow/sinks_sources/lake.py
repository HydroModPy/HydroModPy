"""Lake / reservoir boundary-condition payload for the flow process.

Defines :class:`FlowLakeConfig`, the physics-layer parameters for one MODFLOW 6
LAK lake: bed leakance, initial stage, the surverse / spillway outlets, and the
transient forcings (rainfall, evaporation, runoff, inflow, withdrawal).

File references (geometry polygon, bathymetry, abacus table) live in the data
layer (``data/variables/lake*``); this module holds only the boundary-condition
*parameters*, mirroring :mod:`hydromodpy.physics.flow.sinks_sources.wells`.

The outlets are a discriminated union on ``couttype``:

* :class:`FlowLakeOutletWeir`     -- a fixed-crest weir (``invert``, ``width``),
* :class:`FlowLakeOutletManning`  -- a Manning channel (``invert``, ``width``,
  ``rough``, ``slope``),
* :class:`FlowLakeOutletSpecified`-- a controlled release (``rate`` L^3/T, signed).

``lakeout = 0`` routes the outlet discharge to an external boundary (out of the
model); a positive integer routes it directly to that downstream lake (1-based).

For a *controlled* transfer (a fraction, a cap, or a threshold) the outlet keeps
``lakeout = 0`` (external) and carries an optional ``mover`` spec instead; the LAK
outlet then feeds a MODFLOW 6 MVR record routed to the receiving lake. The two
crossed-weir trick for a partially submerged sill (0 -> 1 and
1 -> 0 at the same invert) is expressed as two plain WEIR outlets, one per lake.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units import FlowRate, Length
from hydromodpy.core.units.leakance import normalize_per_s_unit
from hydromodpy.physics.flow.sinks_sources.flow_barrier import FlowBarrierConfig
from hydromodpy.physics.flow.sinks_sources.wells import FlowWellForcingConfig


class FlowLakeOutletMover(HydroModelBase):
    """A controlled LAK transfer for one outlet, routed through MVR.

    The outlet keeps ``lakeout = 0`` (external) and this spec sends its discharge
    to a receiver through a MODFLOW 6 MVR record. The receiver is either ``lake``
    (1-based downstream lake number, LAK -> LAK) or ``reach`` (1-based downstream
    SFR reach, LAK -> SFR spillway release); exactly one must be set. ``mvrtype``
    picks how much water moves: ``FACTOR`` (a fraction ``value`` of the provider
    flow), ``UPTO`` (capped at ``value``), ``EXCESS`` (only above ``value``) or
    ``THRESHOLD`` (all-or-nothing above ``value``).
    """

    lake: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description="Downstream receiving lake (1-based) for a LAK -> LAK transfer.",
    )
    reach: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description="Downstream receiving SFR reach (1-based) for a LAK -> SFR transfer.",
    )
    mvrtype: Annotated[Literal["FACTOR", "UPTO", "EXCESS", "THRESHOLD"], Profile.USER] = Field(
        default="FACTOR",
        description="MVR transfer rule (FACTOR / UPTO / EXCESS / THRESHOLD).",
    )
    value: Annotated[float, Profile.USER] = Field(
        default=1.0,
        ge=0.0,
        description=(
            "MVR value: the fraction for FACTOR, or the flow rate [L^3/T] for "
            "UPTO / EXCESS / THRESHOLD."
        ),
    )

    @model_validator(mode="after")
    def _validate_receiver(self) -> FlowLakeOutletMover:
        """The mover targets exactly one receiver: a lake or an SFR reach."""
        if (self.lake is None) == (self.reach is None):
            raise ValueError(
                "flow.sinks_sources.lakes outlet mover needs exactly one of lake or reach"
            )
        return self


class FlowLakeOutletWeir(HydroModelBase):
    """A sharp-crest weir outlet: ``Q = (2/3)*Cd*width*sqrt(2g)*d^(3/2)``.

    ``invert`` is the crest elevation (flow is zero while ``stage <= invert``);
    ``width`` is the effective crest length used to calibrate the discharge
    coefficient (``Cd`` is fixed inside MF6).
    """

    couttype: Annotated[Literal["WEIR"], Profile.USER] = Field(
        default="WEIR",
        description="Discriminator tag for the weir outlet type.",
    )
    invert: Annotated[Length, Profile.USER] = Field(..., description="Weir crest elevation [L].")
    width: Annotated[Length, Profile.USER] = Field(
        ..., description="Effective weir crest length [L]."
    )
    lakeout: Annotated[int, Profile.USER] = Field(
        default=0,
        ge=0,
        description=(
            "Downstream destination lake (1-based). 0 = external boundary "
            "(the discharge leaves the model)."
        ),
    )
    mover: Annotated[FlowLakeOutletMover | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional controlled LAK -> LAK transfer routed through MVR "
            "(keep lakeout = 0 when a mover is set)."
        ),
    )


class FlowLakeOutletManning(HydroModelBase):
    """A Manning channel outlet: ``Q ~ (1/rough)*width*d^(5/3)*sqrt(slope)``."""

    couttype: Annotated[Literal["MANNING"], Profile.USER] = Field(
        default="MANNING",
        description="Discriminator tag for the Manning outlet type.",
    )
    invert: Annotated[Length, Profile.USER] = Field(
        ..., description="Channel invert elevation [L]."
    )
    width: Annotated[Length, Profile.USER] = Field(..., description="Channel width [L].")
    rough: Annotated[float, Profile.USER] = Field(
        ..., gt=0.0, description="Manning roughness coefficient n (> 0)."
    )
    slope: Annotated[float, Profile.USER] = Field(
        ..., gt=0.0, description="Channel bed slope (> 0)."
    )
    lakeout: Annotated[int, Profile.USER] = Field(
        default=0,
        ge=0,
        description=(
            "Downstream destination lake (1-based). 0 = external boundary "
            "(the discharge leaves the model)."
        ),
    )
    mover: Annotated[FlowLakeOutletMover | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional controlled LAK -> LAK transfer routed through MVR "
            "(keep lakeout = 0 when a mover is set)."
        ),
    )


class FlowLakeOutletSpecified(HydroModelBase):
    """A specified-flow outlet (controlled release / gate): ``Q = rate``.

    ``rate`` is volumetric [L^3/T] and signed (+ = inflow, - = outflow). A
    transient release schedule may be declared via ``forcing`` instead of a
    constant ``rate``.
    """

    couttype: Annotated[Literal["SPECIFIED"], Profile.USER] = Field(
        default="SPECIFIED",
        description="Discriminator tag for the specified-flow outlet type.",
    )
    rate: Annotated[FlowRate | None, Profile.USER] = Field(
        default=None,
        description="Constant specified outlet rate [L^3/T], signed (+in, -out).",
    )
    forcing: Annotated[FlowWellForcingConfig | None, Profile.DEV] = Field(
        default=None,
        description="Optional transient release schedule resolved at runtime.",
    )
    lakeout: Annotated[int, Profile.USER] = Field(
        default=0,
        ge=0,
        description=(
            "Downstream destination lake (1-based). 0 = external boundary "
            "(the discharge leaves the model)."
        ),
    )
    mover: Annotated[FlowLakeOutletMover | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional controlled LAK -> LAK transfer routed through MVR "
            "(keep lakeout = 0 when a mover is set)."
        ),
    )

    @model_validator(mode="after")
    def _validate_rate_or_forcing(self) -> FlowLakeOutletSpecified:
        """A specified outlet needs exactly one of a constant rate or a forcing."""
        if self.rate is None and self.forcing is None:
            raise ValueError(
                "flow.sinks_sources.lakes outlet 'SPECIFIED' requires either rate or forcing"
            )
        if self.rate is not None and self.forcing is not None:
            raise ValueError(
                "flow.sinks_sources.lakes outlet rate and forcing are mutually exclusive"
            )
        return self


FlowLakeOutletConfig: TypeAlias = Annotated[
    FlowLakeOutletWeir | FlowLakeOutletManning | FlowLakeOutletSpecified,
    Field(
        discriminator="couttype",
        description=("Discriminated union of lake outlet payloads (WEIR, MANNING, or SPECIFIED)."),
    ),
]
"""Discriminated union of lake-outlet payloads."""


class BathymetryReconstructionConfig(HydroModelBase):
    """Opt-in carving of the real lake bed from bathymetry into the grid.

    When set, the loaded ``lake_bathymetry`` raster is resampled onto the lake
    cells and (by default) reconciled to the abacus by area-weighted quantile
    mapping, then carved into the mesh ``top``/``botm`` so the LAK vertical
    exchange happens at the real bed and the groundwater flow lines follow the
    real basin instead of a flat reservoir. The raster must be declared in the
    data layer (``[data.lake_bathymetry]``); a lake without that data and with
    reconstruction enabled raises at build time.
    """

    reconcile_to_abacus: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Re-map the regridded bed so the cell area-vs-elevation distribution "
            "matches the abacus (the abacus is the storage source of truth). When "
            "False, the raw regridded bathymetry is carved as-is."
        ),
    )
    dynamic_area: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Active-littoral (marnage) representation. When True the lake-bed cells "
            "stay ACTIVE with the carved bathymetric bed as their cell top and one "
            "VERTICAL LAK connection each; MODFLOW 6 then toggles recharge/ET per "
            "cell (IWETLAKE) so a cell exchanges with the lake when submerged and "
            "recharges as land when the shoreline recedes below its bed. When False "
            "the footprint is deactivated (fixed-area reservoir, the classic "
            "inactive-footprint carve)."
        ),
    )
    exposed_band_runoff: Annotated[bool, Profile.EXPERT] = Field(
        default=False,
        description=(
            "Shed the overland runoff of the exposed lakebed band directly to the "
            "lake, sized per timestep from the simulated stage via the MODFLOW 6 "
            "BMI API (runoff_rate * exposed_area). Requires dynamic_area and forces "
            "the in-process API runner (serial only). When False the catchment "
            "runoff already covers the footprint area in a lumped, stage-static way."
        ),
    )
    min_thickness: Annotated[float, Profile.USER] = Field(
        default=0.5,
        gt=0.0,
        description=(
            "Minimum layer thickness [L, model units] kept when re-grading a lake "
            "column around the carved bed, so no degenerate (near-zero) cell breaks "
            "the solver. The bed is clamped into [base + min_thickness, top - "
            "min_thickness]."
        ),
    )
    min_pixels: Annotated[int, Profile.USER] = Field(
        default=1,
        ge=1,
        description=(
            "Minimum bathymetry pixels whose centre must fall inside a cell for the "
            "zonal mean to be used; below it a bilinear sample at the cell centroid "
            "is taken instead."
        ),
    )

    @model_validator(mode="after")
    def _validate_exposed_band_runoff(self) -> BathymetryReconstructionConfig:
        """The exposed-band runoff needs the active-littoral representation."""
        if self.exposed_band_runoff and not self.dynamic_area:
            raise ValueError(
                "flow.sinks_sources.lakes.bed_reconstruction.exposed_band_runoff requires "
                "dynamic_area = true (the exposed band only exists with the active-littoral carve)"
            )
        return self


class FlowLakeConfig(HydroModelBase):
    """
    Typed boundary-condition payload for one MODFLOW 6 LAK lake.

    The lake exchanges with the aquifer through its CONNECTIONDATA, parameterized
    by ``bedleak`` (the lake-bed leakance, 1/T). ``stageinit`` is the initial lake
    stage. ``outlets`` declare the surverse / spillway / controlled releases; the
    transient forcings (``rainfall`` and ``evaporation`` as rates L/T, ``runoff``,
    ``inflow`` and ``withdrawal`` as volumetric L^3/T) are optional runtime
    declarations resolved against ``[simulation.time]``.

    File references (geometry polygon, bathymetry raster, stage-volume-area
    abacus, observed levels) are declared separately in the data layer.
    """

    bedleak: Annotated[float, Profile.USER] = Field(
        ...,
        ge=0.0,
        description=(
            "Lake-bed leakance [1/T] = K_bed / thickness_bed. Resistance of the "
            "lake-aquifer interface; the under-dam leakage calibration parameter. "
            "0 means a perfectly sealed lakebed (no leakage)."
        ),
    )
    bedleak_unit: Annotated[str, Profile.USER] = Field(
        default="1/s",
        description=(
            "Unit of bedleak (leakance, 1/T): one of 1/s, 1/day, 1/h, 1/min "
            "(aliases like 1/d accepted). HydroModPy converts it to 1/s for MF6, "
            "so a 1/day leakance is not silently taken as 1/s."
        ),
    )
    stageinit: Annotated[Length, Profile.USER] = Field(..., description="Initial lake stage [L].")
    steady_stage_hold: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Hold the lake stage at stageinit during the steady warm-up period(s) "
            "(LAK status CONSTANT) and re-activate it on the first transient "
            "period. Use for a managed reservoir whose observed initial level is "
            "far from the natural steady equilibrium: the aquifer equilibrates "
            "around the observed stage instead of overriding it."
        ),
    )
    occupied_layers: Annotated[int, Profile.USER] = Field(
        default=1,
        ge=1,
        description=(
            "Number of top grid layers the lake occupies in each of its columns. "
            "1 is a surface lake; a deeper reservoir embedded over several layers "
            "uses a higher count. Must leave at least one active layer below the "
            "lake for the VERTICAL leakage connection."
        ),
    )
    surfdep: Annotated[float | None, Profile.EXPERT] = Field(
        default=None,
        ge=0.0,
        description=(
            "LAK surface depression depth [L] that smooths the dry/wet (marnage) "
            "transition for Newton. Default (None) uses 0.1 m. Raise it (e.g. 0.5 to "
            "1.0 m) to stabilise and speed up the active-littoral steady solve when "
            "many lakebed cells toggle at once; it slightly fuzzes the shoreline."
        ),
    )
    bed_reconstruction: Annotated[BathymetryReconstructionConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional bathymetry-driven bed carving. When set, the real lake bed "
            "is reconstructed from the lake_bathymetry raster (reconciled to the "
            "abacus) and carved into the grid instead of a flat reservoir."
        ),
    )
    outlets: Annotated[list[FlowLakeOutletConfig], Profile.USER] = Field(
        default_factory=list,
        description="Surverse / spillway / controlled-release outlets for this lake.",
    )
    cutoff_wall: Annotated[FlowBarrierConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional dam cutoff wall / grout curtain on the dam axis, modeled as "
            "a MODFLOW 6 HFB (the lake-derived use of FlowBarrierConfig). The "
            "barrier forces the under-dam seepage to dive below the wall instead "
            "of leaking through the top layers."
        ),
    )
    rainfall: Annotated[FlowWellForcingConfig | None, Profile.DEV] = Field(
        default=None,
        description="Optional rainfall rate forcing [L/T] (per unit lake surface).",
    )
    evaporation: Annotated[FlowWellForcingConfig | None, Profile.DEV] = Field(
        default=None,
        description="Optional open-water evaporation rate forcing [L/T].",
    )
    runoff: Annotated[FlowWellForcingConfig | None, Profile.DEV] = Field(
        default=None,
        description="Optional runoff forcing, volumetric [L^3/T].",
    )
    inflow: Annotated[FlowWellForcingConfig | None, Profile.DEV] = Field(
        default=None,
        description="Optional inflow forcing, volumetric [L^3/T].",
    )
    withdrawal: Annotated[FlowWellForcingConfig | None, Profile.DEV] = Field(
        default=None,
        description="Optional withdrawal forcing, volumetric [L^3/T].",
    )

    @field_validator("bedleak_unit")
    @classmethod
    def _validate_bedleak_unit(cls, value: str) -> str:
        """Reject a bedleak unit that is not a leakance (1/T) at config time."""
        normalize_per_s_unit(value)
        return value

    @field_validator("outlets", mode="before")
    @classmethod
    def _coerce_outlets(cls, value):
        """Accept ``None`` and a single mapping as well as a list of outlets."""
        if value is None:
            return []
        if isinstance(value, Mapping):
            return [value]
        return value

    @model_validator(mode="after")
    def _validate_outlet_routing(self) -> FlowLakeConfig:
        """An outlet routes either directly (lakeout) or through a mover, not both."""
        for outlet in self.outlets:
            if outlet.lakeout > 0 and outlet.mover is not None:
                raise ValueError(
                    "flow.sinks_sources.lakes outlet sets both lakeout and mover; "
                    "keep lakeout = 0 when a mover is declared"
                )
        return self


__all__ = [
    "BathymetryReconstructionConfig",
    "FlowLakeConfig",
    "FlowLakeOutletConfig",
    "FlowLakeOutletManning",
    "FlowLakeOutletMover",
    "FlowLakeOutletSpecified",
    "FlowLakeOutletWeir",
]
