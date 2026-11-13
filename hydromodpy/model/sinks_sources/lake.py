"""Lake / reservoir boundary-condition payload for the flow process.

Defines :class:`FlowLakeConfig`, the model parameters for one MODFLOW 6
LAK lake: bed leakance, initial stage, the surverse / spillway outlets, and the
transient forcings (rainfall, evaporation, runoff, inflow, withdrawal).

File references (geometry polygon, bathymetry, abacus table) live in the data
layer (``data/variables/lake*``); this module holds only the boundary-condition
*parameters*, mirroring :mod:`hydromodpy.model.sinks_sources.wells`.

The outlets are a discriminated union on ``kind``, the couttype of MODFLOW 6:

* :class:`FlowLakeOutletWeir`     -- a fixed-crest weir (``invert``, ``width``),
* :class:`FlowLakeOutletManning`  -- a Manning channel (``invert``, ``width``,
  ``rough``, ``slope``),
* :class:`FlowLakeOutletSpecified`-- a controlled release (``rate`` L^3/T, signed).

``lakeout = 0`` routes the outlet discharge to an external boundary (out of the
model); a positive integer routes it directly to that downstream lake (1-based).

For a *controlled* transfer (a fraction, a cap, or a threshold) the outlet keeps
``lakeout = 0`` (external) and carries an optional ``mover`` spec instead; the LAK
outlet then feeds a MODFLOW 6 MVR record routed to the receiving lake. A sill
between two lakes is one WEIR outlet, on the upper lake, with ``lakeout`` naming
the lower one. Two WEIR outlets that spill into each other over the same crest
are refused: above the crest MF6 sends water both ways every time step instead
of routing it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.units.quantities import normalize_per_s_unit
from hydromodpy.core.units.types import FlowRate, Length
from hydromodpy.model.forcing.dated_forcing import (
    SurfaceRateForcing,
    VolumeRateForcing,
    declared_forcing_values,
)
from hydromodpy.model.sinks_sources.flow_barrier import CutoffWallConfig


class FlowLakeOutletMover(HydroModelBase):
    """A controlled LAK transfer for one outlet, routed through MVR.

    The outlet keeps ``lakeout = 0`` (external) and this spec sends its discharge
    to a receiver through a MODFLOW 6 MVR record. The receiver is one of ``lake``
    (1-based downstream lake number, LAK -> LAK), ``reach`` (1-based downstream SFR
    reach, LAK -> SFR spillway release), or ``to_downstream_reach`` (auto-resolve the
    downstream reach on the mesh, robust to remeshing); exactly one must be set.
    ``mvrtype`` picks how much water moves: ``FACTOR`` (a fraction ``value`` of the
    provider flow), ``UPTO`` (capped at ``value``), ``EXCESS`` (only above ``value``)
    or ``THRESHOLD`` (all-or-nothing above ``value``).
    """

    lake: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description=(
            "Number of the lake that receives the transfer, counted from 1 in the order "
            "the lakes are declared."
        ),
        json_schema_extra={"unit": "-"},
    )
    reach: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description=(
            "Number of the SFR reach that receives the transfer, counted from 1. A reach "
            "number changes when the mesh changes; to_downstream_reach does not."
        ),
        json_schema_extra={"unit": "-"},
    )
    to_downstream_reach: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Auto-resolve the LAK -> SFR receiver: route the spillway to the SFR reach on "
            "the foot of the dam, downstream of the cutoff wall when the lake has one. "
            "The SFR network draws a channel to the foot only with rectify_on_mesh; "
            "without a reach on the foot the build stops, it never takes the nearest "
            "reach, which can flow back into the lake. Robust to remeshing, unlike a "
            "fixed reach number. Keep lakeout = 0."
        ),
    )
    discharge_xy: Annotated[tuple[float, float] | None, Profile.EXPERT] = Field(
        default=None,
        description=(
            "Optional explicit spillway discharge point [x, y] in the project CRS. With "
            "to_downstream_reach, the dam foot is located nearest this point instead of "
            "inferred from the domain outlet. Use it when the spillway is not on the "
            "outlet-facing shore, or for a lake away from the catchment outlet."
        ),
    )
    mvrtype: Annotated[Literal["FACTOR", "UPTO", "EXCESS", "THRESHOLD"], Profile.USER] = Field(
        default="FACTOR",
        description="How much of the outlet flow the mover passes to the receiver, given value.",
        json_schema_extra={
            "value_docs": {
                "FACTOR": "Moves the share value (from 0 to 1) of the flow.",
                "UPTO": "Moves the flow, capped at value.",
                "EXCESS": "Moves only the part of the flow above value.",
                "THRESHOLD": "Moves value once the flow exceeds it, and nothing below it.",
            }
        },
    )
    value: Annotated[float, Profile.USER] = Field(
        default=1.0,
        ge=0.0,
        description=(
            "Amount of the transfer rule: a share from 0 to 1 for FACTOR, a flow rate in "
            "m3/s for UPTO, EXCESS and THRESHOLD."
        ),
        json_schema_extra={"unit": "- or m3/s"},
    )

    @model_validator(mode="after")
    def _validate_receiver(self) -> FlowLakeOutletMover:
        """The mover targets exactly one receiver: a lake, an SFR reach, or auto-downstream."""
        set_count = (self.lake is not None) + (self.reach is not None) + self.to_downstream_reach
        if set_count != 1:
            raise ValueError(
                "flow.sinks_sources.lakes outlet mover needs exactly one of lake, reach, "
                "or to_downstream_reach"
            )
        return self

    @model_validator(mode="after")
    def _validate_factor_value(self) -> FlowLakeOutletMover:
        """A FACTOR transfer moves a fraction, so its value must be in [0, 1]."""
        if self.mvrtype == "FACTOR" and not (0.0 <= self.value <= 1.0):
            raise ValueError(
                "flow.sinks_sources.lakes outlet mover value must be in [0, 1] for a "
                "FACTOR transfer"
            )
        return self


class FlowLakeOutletWeir(HydroModelBase):
    """A sharp-crest weir outlet: ``Q = (2/3)*Cd*width*sqrt(2g)*d^(3/2)``.

    ``invert`` is the crest elevation (flow is zero while ``stage <= invert``);
    ``width`` is the effective crest length used to calibrate the discharge
    coefficient (``Cd`` is fixed inside MF6).
    """

    kind: Annotated[Literal["WEIR"], Profile.USER] = Field(
        default="WEIR",
        description="This outlet is a weir one (couttype of MODFLOW 6 LAK).",
        json_schema_extra=field_metadata(
            renamed_from=["flow.sinks_sources.lakes.outlets.couttype"]
        ),
    )
    invert: Annotated[Length, Profile.USER] = Field(
        ...,
        description=(
            "Elevation of the weir crest, in metres. No water leaves while the stage is "
            "at or below it."
        ),
        examples=[45.0],
    )
    width: Annotated[Length, Profile.USER] = Field(
        ...,
        description=(
            "Effective length of the weir crest, in metres. The discharge grows in "
            "proportion to it."
        ),
        examples=[10.0],
    )
    lakeout: Annotated[int, Profile.USER] = Field(
        default=0,
        ge=0,
        description=(
            "Number of the lake that receives the discharge, counted from 1 in the order "
            "the lakes are declared. 0 sends the discharge out of the model. A sill "
            "between two lakes is one outlet, on the upper lake; two WEIR outlets that "
            "spill into each other over the same crest are refused."
        ),
        json_schema_extra={"unit": "-"},
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

    kind: Annotated[Literal["MANNING"], Profile.USER] = Field(
        default="MANNING",
        description="This outlet is a Manning one (couttype of MODFLOW 6 LAK).",
        json_schema_extra=field_metadata(
            renamed_from=["flow.sinks_sources.lakes.outlets.couttype"]
        ),
    )
    invert: Annotated[Length, Profile.USER] = Field(
        ...,
        description="Elevation of the outlet channel bed, in meters. No water leaves below it.",
        examples=[45.0],
    )
    width: Annotated[Length, Profile.USER] = Field(
        ...,
        description="Width of the outlet channel, in meters.",
        examples=[5.0],
    )
    rough: Annotated[float, Profile.USER] = Field(
        ...,
        gt=0.0,
        description=(
            "Manning roughness coefficient n of the outlet channel. A higher value "
            "slows the discharge."
        ),
        examples=[0.035],
        json_schema_extra={"unit": "s/m^(1/3)"},
    )
    slope: Annotated[float, Profile.USER] = Field(
        ...,
        gt=0.0,
        description="Slope of the outlet channel bed, in meters of drop per meter of length.",
        examples=[0.001],
        json_schema_extra={"unit": "-"},
    )
    lakeout: Annotated[int, Profile.USER] = Field(
        default=0,
        ge=0,
        description=(
            "Number of the lake that receives the discharge, counted from 1 in the order "
            "the lakes are declared. 0 sends the discharge out of the model."
        ),
        json_schema_extra={"unit": "-"},
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

    ``rate`` is volumetric [L^3/T] and signed (+ enters the lake, - leaves it). A
    transient release schedule may be declared via ``forcing`` instead of a
    constant ``rate``.
    """

    kind: Annotated[Literal["SPECIFIED"], Profile.USER] = Field(
        default="SPECIFIED",
        description="This outlet is a specified-flow one (couttype of MODFLOW 6 LAK).",
        json_schema_extra=field_metadata(
            renamed_from=["flow.sinks_sources.lakes.outlets.couttype"]
        ),
    )
    rate: Annotated[FlowRate | None, Profile.USER] = Field(
        default=None,
        description=(
            "Constant rate of the outlet, in m3/s. A positive rate enters the lake, a "
            "negative one leaves it."
        ),
    )
    forcing: Annotated[VolumeRateForcing | None, Profile.DEV] = Field(
        default=None,
        description="Optional transient release schedule resolved at runtime.",
    )
    lakeout: Annotated[int, Profile.USER] = Field(
        default=0,
        ge=0,
        description=(
            "Number of the lake that receives the discharge, counted from 1 in the order "
            "the lakes are declared. 0 sends the discharge out of the model."
        ),
        json_schema_extra={"unit": "-"},
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
        discriminator="kind",
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
    bank_seepage: Annotated[bool, Profile.USER, VisibleWhen("dynamic_area", True)] = Field(
        default=True,
        description=(
            "Also emit HORIZONTAL (bank) LAK connections on the active-littoral "
            "footprint, in addition to the VERTICAL (bed) ones, so the lake exchanges "
            "with the aquifer through both the bed AND the banks (the physical case). "
            "Sealed at the cutoff wall (dam) when one is declared. Only applies with "
            "dynamic_area = true; a fixed-area lake always emits both. Set False to "
            "keep the bed-only marnage representation (the bedleak then absorbs the "
            "bank contribution)."
        ),
    )
    min_thickness: Annotated[float, Profile.USER] = Field(
        default=0.5,
        gt=0.0,
        description=(
            "Minimum layer thickness, in metres, held by EVERY layer when "
            "re-grading a lake column around the carved bed, so no degenerate "
            "(near-zero) cell breaks the solver. The bed is clamped into the band "
            "the column can hold at that floor, i.e. [base + n_active * "
            "min_thickness, top - n_occupied * min_thickness]; a column too thin "
            "for it raises at build time. Raising this value moves the carved bed "
            "away from the bathymetry (the build logs the shift)."
        ),
        json_schema_extra={"unit": "m"},
    )
    min_pixels: Annotated[int, Profile.USER] = Field(
        default=1,
        ge=1,
        description=(
            "Minimum bathymetry pixels whose centre must fall inside a cell for the "
            "zonal mean to be used; below it a bilinear sample at the cell centroid "
            "is taken instead. A count of pixels."
        ),
        json_schema_extra={"unit": "-"},
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


LAKE_FORCING_SIGN_CONVENTION: dict[str, str] = {
    "rainfall": "the rate that falls on the lake",
    "evaporation": "the largest rate that evaporates from the lake",
    "runoff": "the rate that runs off into the lake",
    "inflow": "the rate that flows into the lake",
    "withdrawal": "the largest rate taken out of the lake",
}
"""Lake forcings, each read by MODFLOW 6 LAK as a value of zero or more."""


def lake_forcing_sign_refusal(keyword: str, value: float, *, where: str = "") -> str:
    """Return the message that refuses a negative lake forcing."""
    location = f" ({where})" if where else ""
    return (
        f"Lake {keyword} = {value:g}{location} is negative. MODFLOW 6 LAK reads "
        f"{keyword.upper()} as {LAKE_FORCING_SIGN_CONVENTION[keyword]}, zero or more, "
        f"and stops on a negative value. Write {keyword} as a positive rate."
    )


class FlowLakeConfig(HydroModelBase):
    """
    Typed boundary-condition payload for one MODFLOW 6 LAK lake.

    The lake exchanges with the aquifer through its CONNECTIONDATA, parameterized
    by ``bedleak`` (the lake-bed leakance, 1/T). ``initial_stage`` is the initial lake
    stage. ``outlets`` declare the surverse / spillway / controlled releases; the
    transient forcings (``rainfall`` and ``evaporation`` as rates L/T, ``runoff``,
    ``inflow`` and ``withdrawal`` as volumetric L^3/T) are optional runtime
    declarations resolved against ``[simulation.time]``.

    File references (geometry polygon, bathymetry raster, stage-volume-area
    abacus, observed levels) are declared separately in the data layer.
    """

    enabled: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Whether this lake is built. Declaring it is what activates it. false keeps the table "
            "and builds nothing from it."
        ),
    )
    bedleak: Annotated[float, Profile.USER] = Field(
        ...,
        ge=0.0,
        description=(
            "Lake-bed leakance [1/T] = K_bed / thickness_bed. Resistance of the "
            "lake-aquifer interface over the whole lake bed, the handle of the "
            "lake-aquifer exchange. The flow through or under the dam is set by "
            "the cutoff_wall and the aquifer, not by this value. "
            "0 means a perfectly sealed lakebed (no leakage)."
        ),
        json_schema_extra=field_metadata(
            calibrable=Calibrable(
                search_space="log",
                sampling="log_uniform",
                units="1/s",
                unit_field="bedleak_unit",
            )
        ),
        examples=[1.0e-6],
    )
    bedleak_unit: Annotated[str, Profile.USER] = Field(
        default="1/s",
        description=(
            "Unit of bedleak (leakance, 1/T): one of 1/s, 1/day, 1/h, 1/min "
            "(aliases like 1/d accepted). HydroModPy converts it to 1/s for MF6, "
            "so a 1/day leakance is not silently taken as 1/s."
        ),
    )
    initial_stage: Annotated[Length, Profile.USER] = Field(
        ...,
        description=(
            "Lake stage at the start of the run: the elevation of the water surface, in "
            "metres. When the first period is steady, the steady solve sets the stage and "
            "this value is only its first guess, unless steady_stage_hold holds it."
        ),
        examples=[45.0],
        json_schema_extra=field_metadata(renamed_from=["flow.sinks_sources.lakes.stageinit"]),
    )
    steady_stage_hold: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Hold the lake stage at initial_stage during the steady warm-up period(s) "
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
            "lake for the VERTICAL leakage connection. A count of layers."
        ),
        json_schema_extra={"unit": "-"},
    )
    fill_enclosed_cells: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Fill cells enclosed by the lake footprint (the polygon's interior "
            "rings / islands) so the lake is contiguous. Off by default: interior "
            "rings stay active aquifer (real islands). Enable to drop sub-grid "
            "islands and classification pockets that would otherwise be isolated "
            "non-lake cells inside the lake."
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
        json_schema_extra=field_metadata(unit="m"),
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
    cutoff_wall: Annotated[CutoffWallConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional dam cutoff wall / grout curtain on the dam axis, modeled as "
            "a MODFLOW 6 HFB laid on the lake shore. The barrier forces the "
            "under-dam seepage to dive below the wall instead of leaking through "
            "the top layers. The flow across its faces is published per layer as "
            "the cutoff_wall_flow series."
        ),
        json_schema_extra=field_metadata(stability="experimental"),
    )
    rainfall: Annotated[SurfaceRateForcing | None, Profile.USER] = Field(
        default=None,
        description=(
            "Rainfall on the lake over time, as a rate per unit of lake surface (m/s in SI). "
            "It wins over the rainfall taken from [data.precipitation]."
        ),
    )
    evaporation: Annotated[SurfaceRateForcing | None, Profile.USER] = Field(
        default=None,
        description=(
            "Open-water evaporation over time, as a rate per unit of lake surface "
            "(m/s in SI). It wins over the evaporation taken from [data.etp]."
        ),
    )
    runoff: Annotated[VolumeRateForcing | None, Profile.USER] = Field(
        default=None,
        description=(
            "Runoff that enters the lake over time, as a volume per time (m3/s in SI). "
            "It wins over the runoff taken from [data.runoff]."
        ),
    )
    inflow: Annotated[VolumeRateForcing | None, Profile.USER] = Field(
        default=None,
        description="Other inflow to the lake over time, as a volume per time (m3/s in SI).",
    )
    withdrawal: Annotated[VolumeRateForcing | None, Profile.USER] = Field(
        default=None,
        description=(
            "Rate of water taken from the lake over time, as a volume per time "
            "(m3/s in SI), written positive. It is passed to the WITHDRAWAL setting of "
            "MODFLOW 6 LAK, which reads every lake forcing as zero or more."
        ),
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

    @model_validator(mode="after")
    def _refuse_negative_forcings(self) -> FlowLakeConfig:
        """Refuse a negative lake forcing: MODFLOW 6 LAK stops on one."""
        for keyword in LAKE_FORCING_SIGN_CONVENTION:
            forcing = getattr(self, keyword)
            negative = [value for value in declared_forcing_values(forcing) if value < 0.0]
            if negative:
                raise ValueError(lake_forcing_sign_refusal(keyword, negative[0]))
        return self


__all__ = [
    "LAKE_FORCING_SIGN_CONVENTION",
    "BathymetryReconstructionConfig",
    "FlowLakeConfig",
    "FlowLakeOutletConfig",
    "FlowLakeOutletManning",
    "FlowLakeOutletMover",
    "FlowLakeOutletSpecified",
    "FlowLakeOutletWeir",
    "lake_forcing_sign_refusal",
]
