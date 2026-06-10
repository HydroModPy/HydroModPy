"""Streamflow-routing (SFR) boundary-condition payload for the flow process.

Defines :class:`FlowReachNetworkConfig`, the physics-layer parameters for one
MODFLOW 6 SFR stream network: the delineation thresholds, the streambed
hydraulics (Manning roughness, conductivity, thickness), the reach width law, the
transient forcings (headwater inflow, runoff, rainfall, evaporation) and the
optional MVR coupling to a downstream lake.

This module holds only the boundary-condition *parameters*, mirroring
:mod:`hydromodpy.physics.flow.sinks_sources.lake` and
:mod:`hydromodpy.physics.flow.sinks_sources.wells`. The reach geometry and the
network topology are computed in the spatial layer (from the DEM and D8 flow
products) and mapped onto the DISV mesh in the solver builder; none of that lives
here.

SFR is lake-independent by construction: a network with ``outflow_to_lake = None``
routes streamflow with no lake at all. The lake coupling is a single MVR record
(SFR provider, LAK receiver), expressed by ``outflow_to_lake``.

The reach width is a discriminated union on ``kind``:

* :class:`FlowReachWidthConstant`  -- a uniform width,
* :class:`FlowReachWidthByOrder`   -- a width per Strahler stream order,
* :class:`FlowReachWidthPowerLaw`  -- a hydraulic-geometry power law of drainage
  area (``width = coef * area_km2 ** exp``).
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units import Length
from hydromodpy.core.units.hydraulic_conductivity import normalize_m_per_s_unit
from hydromodpy.physics.flow.sinks_sources.wells import (
    FlowWellForcingConfig,
    FlowWellLocation,
)

_MVR_RULES = ("FACTOR", "UPTO", "EXCESS", "THRESHOLD")


class FlowReachWidthConstant(HydroModelBase):
    """A uniform reach width applied to every reach."""

    kind: Annotated[Literal["constant"], Profile.USER] = Field(
        default="constant",
        description="Discriminator tag for the constant reach-width law.",
    )
    value: Annotated[Length, Profile.USER] = Field(
        ..., description="Uniform reach width rwid [L] for all reaches."
    )


class FlowReachWidthByOrder(HydroModelBase):
    """A reach width keyed by Strahler stream order."""

    kind: Annotated[Literal["by_order"], Profile.USER] = Field(
        default="by_order",
        description="Discriminator tag for the per-Strahler-order width law.",
    )
    widths: Annotated[dict[int, Length], Profile.USER] = Field(
        ...,
        description="Reach width rwid [L] per Strahler order (e.g. {1: '1 m', 2: '3 m'}).",
    )

    @field_validator("widths")
    @classmethod
    def _validate_widths(cls, value: dict[int, Length]) -> dict[int, Length]:
        """At least one order must be declared."""
        if not value:
            raise ValueError(
                "flow.sinks_sources.sfr width 'by_order' needs at least one Strahler order"
            )
        return value


class FlowReachWidthPowerLaw(HydroModelBase):
    """A hydraulic-geometry width: ``rwid = coef * drainage_area_km2 ** exp`` [m]."""

    kind: Annotated[Literal["power_law"], Profile.USER] = Field(
        default="power_law",
        description="Discriminator tag for the drainage-area power-law width.",
    )
    coef: Annotated[float, Profile.USER] = Field(
        ..., gt=0.0, description="Coefficient [m] of the width power law (> 0)."
    )
    exp: Annotated[float, Profile.USER] = Field(
        default=0.5,
        description="Exponent of the drainage-area (km^2) power law. Typical ~0.5.",
    )


FlowReachWidthConfig: TypeAlias = Annotated[
    FlowReachWidthConstant | FlowReachWidthByOrder | FlowReachWidthPowerLaw,
    Field(
        discriminator="kind",
        description="Discriminated union of reach-width laws (constant, by_order, power_law).",
    ),
]
"""Discriminated union of reach-width laws."""


class FlowReachConfig(HydroModelBase):
    """One explicit reach row, used to bypass automatic network delineation.

    Connectivity is given by 1-based reach ids. ``upstream`` lists the reaches
    whose downstream end feeds this reach; ``downstream`` lists the reaches this
    reach feeds. The two must be reciprocal across the network.
    """

    cell: Annotated[FlowWellLocation | None, Profile.USER] = Field(
        default=None,
        description=(
            "DISV cell the reach exchanges with (streambed leakage). None = no "
            "aquifer connection (cellid 'none', pure routing)."
        ),
    )
    length: Annotated[Length, Profile.USER] = Field(..., description="Reach length rlen [L].")
    width: Annotated[Length, Profile.USER] = Field(..., description="Reach width rwid [L].")
    slope: Annotated[float, Profile.USER] = Field(
        ..., gt=0.0, description="Reach gradient rgrd [-] (> 0)."
    )
    top: Annotated[Length, Profile.USER] = Field(..., description="Streambed top rtp [L].")
    upstream: Annotated[list[int], Profile.USER] = Field(
        default_factory=list,
        description="1-based ids of reaches whose downstream end feeds this reach.",
    )
    downstream: Annotated[list[int], Profile.USER] = Field(
        default_factory=list,
        description="1-based ids of reaches this reach feeds.",
    )
    ustrf: Annotated[float, Profile.USER] = Field(
        default=1.0,
        ge=0.0,
        description="Upstream fraction routed to this reach (siblings must sum to 1.0).",
    )


class FlowReachDiversionConfig(HydroModelBase):
    """An SFR-to-SFR diversion: a controlled split from one reach to another."""

    reach: Annotated[int, Profile.USER] = Field(
        ..., ge=1, description="Source reach (1-based) the diversion leaves from."
    )
    to_reach: Annotated[int, Profile.USER] = Field(
        ...,
        ge=1,
        description="Receiver reach (1-based); must be a downstream connection of reach.",
    )
    cprior: Annotated[Literal["FRACTION", "EXCESS", "THRESHOLD", "UPTO"], Profile.USER] = Field(
        default="FRACTION",
        description="Diversion priority rule (FRACTION / EXCESS / THRESHOLD / UPTO).",
    )
    divflow: Annotated[FlowWellForcingConfig | None, Profile.DEV] = Field(
        default=None,
        description="Per-period diversion flow [L^3/T] (or fraction for FRACTION).",
    )


class FlowReachNetworkConfig(HydroModelBase):
    """Typed boundary-condition payload for one MODFLOW 6 SFR stream network.

    The network is either delineated automatically from the DEM / D8 flow
    products (set a stream threshold) or supplied explicitly through ``reaches``.
    Reaches exchange with the aquifer through their streambed conductance
    (``streambed_k`` / ``streambed_thickness``) unless ``connected_to_aquifer`` is
    False. The transient forcings (``headwater_inflow``, ``runoff`` as volumetric
    L^3/T; ``rainfall``, ``evaporation`` as rates L/T) are optional runtime
    declarations resolved against ``[simulation.time]``.

    ``outflow_to_lake`` is the only lake-aware field: when set, the terminal reach
    feeds that lake (1-based) through an MVR record (SFR -> LAK). When None, the
    network outflow leaves the model and SFR runs with no lake at all.
    """

    # --- Delineation knobs -------------------------------------------------- #
    stream_threshold_km2: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Drainage-area threshold [km^2] for stream initiation. Exactly one of "
            "stream_threshold_km2 / stream_threshold_cells must be set when reaches "
            "are delineated automatically."
        ),
    )
    stream_threshold_cells: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description="Alternative stream-initiation threshold as a flow-accumulation cell count.",
    )
    min_reach_length: Annotated[Length, Profile.USER] = Field(
        default="0 m",
        description="Prune reaches shorter than this [L] (0 keeps all reaches).",
    )

    # --- Streambed hydraulics ---------------------------------------------- #
    manning: Annotated[float, Profile.USER] = Field(
        default=0.035,
        gt=0.0,
        description="Manning roughness coefficient n [T/L^(1/3)] (> 0). Default 0.035.",
    )
    streambed_k: Annotated[float, Profile.USER] = Field(
        default=1e-6,
        ge=0.0,
        description=(
            "Streambed hydraulic conductivity rhk [L/T]. 0 = no reach-aquifer "
            "leakage (pure routing)."
        ),
    )
    streambed_k_unit: Annotated[str, Profile.USER] = Field(
        default="m/s",
        description=(
            "Unit of streambed_k (velocity, L/T): m/s, m/day, m/h... HydroModPy "
            "converts it to m/s for MF6, so a m/day value is not taken as m/s."
        ),
    )
    streambed_thickness: Annotated[Length, Profile.USER] = Field(
        default="1 m",
        description="Streambed thickness rbth [L] (> 0).",
    )
    min_slope: Annotated[float, Profile.USER] = Field(
        default=1e-4,
        gt=0.0,
        description="Floor for the reach gradient rgrd [-] after monotone-downhill conditioning.",
    )

    width: Annotated[FlowReachWidthConfig, Profile.USER] = Field(
        default_factory=lambda: FlowReachWidthConstant(value="1 m"),
        description="How the reach width rwid [L] is set (constant / by_order / power_law).",
    )

    connected_to_aquifer: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="If False every reach uses cellid 'none' (routing only, no streambed leakage).",
    )
    route_drainage: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Route the hillslope drainage (DRN) discharge into the stream network: "
            "every remaining DRN cell hands its outflow to the NEAREST reach "
            "through an MVR record (FACTOR 1.0) instead of leaving the model. "
            "This is the surface re-infiltration / runon convergence of drained "
            "water towards the river; without it only the reach cells' streambed "
            "captures baseflow and the rest of the catchment discharge is lost."
        ),
    )
    storage: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Enable the channel-storage term (transient first period / SIMPLE only).",
    )

    # --- Forcings (resolved at runtime) ------------------------------------ #
    headwater_inflow: Annotated[FlowWellForcingConfig | None, Profile.DEV] = Field(
        default=None,
        description="External inflow [L^3/T] injected at the headwater reach(es).",
    )
    runoff: Annotated[FlowWellForcingConfig | None, Profile.DEV] = Field(
        default=None,
        description="Diffuse overland inflow [L^3/T], distributed per reach by length.",
    )
    rainfall: Annotated[FlowWellForcingConfig | None, Profile.DEV] = Field(
        default=None,
        description="Rainfall rate [L/T] on the reach surface.",
    )
    evaporation: Annotated[FlowWellForcingConfig | None, Profile.DEV] = Field(
        default=None,
        description="Open-channel evaporation rate [L/T] (positive, subtracted).",
    )

    # --- Explicit network override ----------------------------------------- #
    reaches: Annotated[list[FlowReachConfig] | None, Profile.DEV] = Field(
        default=None,
        description="Explicit reach table; bypasses delineation. None = delineate from the DEM.",
    )
    diversions: Annotated[list[FlowReachDiversionConfig], Profile.USER] = Field(
        default_factory=list,
        description="SFR-to-SFR diversions (controlled splits). Empty = none.",
    )

    # --- Lake coupling ------------------------------------------------------ #
    outflow_to_lake: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description=(
            "1-based lake number the terminal reach feeds via MVR (SFR -> LAK). "
            "None = the network outflow leaves the model (EXT-OUTFLOW)."
        ),
    )
    outflow_mvrtype: Annotated[Literal["FACTOR", "UPTO", "EXCESS", "THRESHOLD"], Profile.USER] = (
        Field(
            default="FACTOR",
            description="MVR transfer rule for the SFR -> LAK coupling.",
        )
    )
    outflow_value: Annotated[float, Profile.USER] = Field(
        default=1.0,
        ge=0.0,
        description=(
            "MVR value: the fraction for FACTOR, or the flow rate [L^3/T] for "
            "UPTO / EXCESS / THRESHOLD."
        ),
    )

    @field_validator("streambed_k_unit")
    @classmethod
    def _validate_streambed_k_unit(cls, value: str) -> str:
        """Reject a streambed_k unit that is not a velocity (L/T) at config time."""
        normalize_m_per_s_unit(value)
        return value

    @model_validator(mode="after")
    def _validate_threshold(self) -> FlowReachNetworkConfig:
        """Delineation needs exactly one threshold; an explicit network needs none."""
        if self.reaches is not None:
            return self
        has_km2 = self.stream_threshold_km2 is not None
        has_cells = self.stream_threshold_cells is not None
        if has_km2 == has_cells:
            raise ValueError(
                "flow.sinks_sources.sfr needs exactly one of stream_threshold_km2 / "
                "stream_threshold_cells when reaches are delineated automatically"
            )
        return self

    @model_validator(mode="after")
    def _validate_outflow(self) -> FlowReachNetworkConfig:
        """A FACTOR coupling moves a fraction, so its value must be in [0, 1]."""
        if (
            self.outflow_to_lake is not None
            and self.outflow_mvrtype == "FACTOR"
            and not (0.0 <= self.outflow_value <= 1.0)
        ):
            raise ValueError(
                "flow.sinks_sources.sfr outflow_value must be in [0, 1] for a FACTOR coupling"
            )
        return self


__all__ = [
    "FlowReachConfig",
    "FlowReachDiversionConfig",
    "FlowReachNetworkConfig",
    "FlowReachWidthByOrder",
    "FlowReachWidthConfig",
    "FlowReachWidthConstant",
    "FlowReachWidthPowerLaw",
]
