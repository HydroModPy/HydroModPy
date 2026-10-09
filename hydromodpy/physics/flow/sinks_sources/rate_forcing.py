"""Forcings given as a rate per unit of surface, a length per time.

MODFLOW 6 reads the rainfall and the evaporation of a lake or of a stream reach
as a length per time (L/T): the package multiplies the rate by the wet surface.
The well forcings next door hold a volume per time (L3/T). These variants take
the same four shapes (constant, csv, piecewise, seasonal) with a value and a
``units`` in length per time, so ``"2 mm/day"`` is read as a rate.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, ClassVar

from pydantic import AfterValidator, Field

from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units.hydraulic_conductivity import (
    M_PER_S_CANONICAL_UNITS,
    normalize_m_per_s_unit,
)
from hydromodpy.core.units.types import FluxDensityMPerS
from hydromodpy.physics.flow.sinks_sources.wells import (
    FlowWellForcingConstantConfig,
    FlowWellForcingCsvConfig,
    FlowWellForcingPiecewiseConfig,
    FlowWellForcingSeasonalConfig,
    FlowWellForcingSegment,
)


def _check_rate_unit(value: str | None) -> str | None:
    """Refuse a unit that is not a length per time."""
    if value is None:
        return None
    try:
        normalize_m_per_s_unit(value)
    except ValueError as exc:
        allowed = ", ".join(M_PER_S_CANONICAL_UNITS)
        raise ValueError(
            f"units = {value!r} is not a rate per unit of surface. Write a length per "
            f"time, one of: {allowed}."
        ) from exc
    return value


RateUnit = Annotated[str | None, AfterValidator(_check_rate_unit)]
"""Unit of a rate forcing, a length per time such as 'mm/day'."""

_RATE_UNITS_DESCRIPTION = (
    "Unit of the forcing values, a length per time such as 'mm/day' or 'm/s'. Values "
    "are converted to m/s when the run starts. Unset, the values are read in m/s."
)


class FlowRateForcingConstantConfig(FlowWellForcingConstantConfig):
    """One constant rate per unit of surface, applied to every stress period."""

    forcing_si_unit: ClassVar[str] = "m/s"

    value: Annotated[FluxDensityMPerS, Profile.USER] = Field(
        ...,
        description=(
            "Rate applied to every stress period, as a length per time. A text value "
            "carries its unit, such as '2 mm/day'. A bare number is read in the unit "
            "that units names, else in m/s."
        ),
        examples=["2 mm/day"],
    )
    units: Annotated[RateUnit, Profile.USER] = Field(
        default=None, description=_RATE_UNITS_DESCRIPTION
    )


class FlowRateForcingCsvConfig(FlowWellForcingCsvConfig):
    """CSV-backed rate forcing resolved at runtime against simulation.time."""

    units: Annotated[RateUnit, Profile.USER] = Field(
        default=None, description=_RATE_UNITS_DESCRIPTION
    )


FlowRateForcingSubConfig = Annotated[
    FlowRateForcingConstantConfig | FlowRateForcingCsvConfig,
    Field(
        discriminator="kind",
        description="Constant or csv rate nested inside one piecewise segment.",
    ),
]
"""Discriminated rate sub-forcing allowed inside a piecewise segment."""


class FlowRateForcingSegment(FlowWellForcingSegment):
    """One dated segment of a piecewise rate forcing."""

    forcing: Annotated[FlowRateForcingSubConfig, Profile.USER] = Field(
        ...,
        description="Rate for this segment, discriminated by 'kind' (constant or csv).",
    )


class FlowRateForcingPiecewiseConfig(FlowWellForcingPiecewiseConfig):
    """Ordered dated segments of a rate, each a constant or a csv."""

    forcing_unit_normalizer: ClassVar[Callable[[str], str]] = staticmethod(normalize_m_per_s_unit)

    segments: Annotated[list[FlowRateForcingSegment], Profile.USER] = Field(
        ...,
        min_length=1,
        description="Date-ordered segments covering the simulation window.",
    )
    units: Annotated[RateUnit, Profile.USER] = Field(
        default=None, description=_RATE_UNITS_DESCRIPTION
    )


class FlowRateForcingSeasonalConfig(FlowWellForcingSeasonalConfig):
    """Calendar month or season to rate mapping repeated across years."""

    units: Annotated[RateUnit, Profile.USER] = Field(
        default=None, description=_RATE_UNITS_DESCRIPTION
    )


FlowRateForcingConfig = Annotated[
    FlowRateForcingConstantConfig
    | FlowRateForcingCsvConfig
    | FlowRateForcingPiecewiseConfig
    | FlowRateForcingSeasonalConfig,
    Field(
        discriminator="kind",
        description=(
            "Rate per unit of surface over time (constant, csv, piecewise or seasonal), "
            "in length per time."
        ),
    ),
]
"""Discriminated union of rate forcings, in length per time."""

__all__ = [
    "FlowRateForcingConfig",
    "FlowRateForcingConstantConfig",
    "FlowRateForcingCsvConfig",
    "FlowRateForcingPiecewiseConfig",
    "FlowRateForcingSeasonalConfig",
    "FlowRateForcingSegment",
    "RateUnit",
]
