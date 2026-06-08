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
from hydromodpy.physics.flow.sinks_sources.wells import FlowWellForcingConfig


class FlowLakeOutletMover(HydroModelBase):
    """A controlled LAK -> LAK transfer for one outlet, routed through MVR.

    The outlet keeps ``lakeout = 0`` (external) and this spec sends its discharge
    to ``lake`` (1-based downstream lake number) through a MODFLOW 6 MVR record.
    ``mvrtype`` picks how much water moves: ``FACTOR`` (a fraction ``value`` of the
    provider flow), ``UPTO`` (capped at ``value``), ``EXCESS`` (only above
    ``value``) or ``THRESHOLD`` (all-or-nothing above ``value``).
    """

    lake: Annotated[int, Profile.USER] = Field(
        ...,
        ge=1,
        description="Downstream receiving lake (1-based) for the MVR transfer.",
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
    outlets: Annotated[list[FlowLakeOutletConfig], Profile.USER] = Field(
        default_factory=list,
        description="Surverse / spillway / controlled-release outlets for this lake.",
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
    "FlowLakeConfig",
    "FlowLakeOutletConfig",
    "FlowLakeOutletManning",
    "FlowLakeOutletMover",
    "FlowLakeOutletSpecified",
    "FlowLakeOutletWeir",
]
