"""One quantity that varies over the stress periods, read the same way wherever it is mounted.

:data:`TimeSeriesForcing` is the one shape: a constant, a CSV record, dated segments
or a calendar, tagged by ``kind``. What differs from one mount to another is the
quantity, so a mount says how to read a value. :data:`VolumeRateForcing` reads a
volume per time, :data:`SurfaceRateForcing` a length per time and :data:`HeadForcing`
a length. The JSON Schema holds one set of tables, and the mounts refer to them.

A bare number is in the unit ``units`` names. With no ``units``, it keeps the unit its
mount reads: m3/s, m/s or m. A value written as a text with its unit is stored in SI,
and ``units`` then names the SI unit.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, ClassVar, Literal, TypeAlias

import pandas as pd
from pydantic import AfterValidator, Field, TypeAdapter, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import NonEmptyStr
from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.core.units.quantities import (
    M_PER_S_CANONICAL_UNITS,
    normalize_length_unit,
    normalize_m3_per_s_unit,
    normalize_m_per_s_unit,
)
from hydromodpy.core.units.types import FluxDensityMPerS, LengthMeters, VolumetricFlowM3PerSecond

FlowTimeAggregate: TypeAlias = Literal["mean", "last"]

_UNITS_DESCRIPTION = (
    "Unit of the values: a volume per time such as 'm3/day' for a flow, a length per time "
    "such as 'mm/day' for a rate on a surface, a length for a head. Values are converted to "
    "SI when the run starts. Unset, a well forcing takes the well's units, a boundary head "
    "the boundary's, and the others read SI."
)
_VALUE_UNIT = "in units, or m3/s, m/s, m by mount"


class ConstantForcing(HydroModelBase):
    """One value applied to every stress period."""

    kind: Annotated[Literal["constant"], Profile.USER] = Field(
        default="constant",
        description="This forcing is one value, kept over every stress period.",
    )
    value: Annotated[float | str, Profile.USER] = Field(
        ...,
        description=(
            "Value applied to every stress period. A text carries its unit, such as "
            "'2 mm/day' or '100 m**3/day'. A bare number is in the unit that units names, "
            "else in the unit its table reads: m3/s for a flow, m/s for a rate on a "
            "surface, m for a head. The sign follows the table: a well rate is negative "
            "when it pumps, and a rate whose name says its direction, such as a "
            "withdrawal or an evaporation, is zero or more."
        ),
        examples=["2 mm/day", -0.001],
        json_schema_extra=field_metadata(unit=_VALUE_UNIT),
    )
    units: Annotated[str | None, Profile.USER] = Field(default=None, description=_UNITS_DESCRIPTION)


class CsvForcing(HydroModelBase):
    """A dated record read from a CSV file and aligned on the stress periods."""

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "fill_method": (
            "no step reads it. A stress period with no sample takes the sample in force, "
            "and simulation.time.coverage_policy decides what happens before or after the "
            "record."
        ),
    }

    kind: Annotated[Literal["csv"], Profile.USER] = Field(
        default="csv",
        description="This forcing is a dated record read from a CSV file.",
    )
    path_file: Annotated[Path, Profile.USER, InputFile(role="forcing", category="data")] = Field(
        ...,
        description=(
            "CSV file of the dated values. Each stress period takes the aggregate of the "
            "samples that fall inside it."
        ),
        examples=["forcing.csv"],
    )
    sep: Annotated[NonEmptyStr, Profile.DEV] = Field(default=",", description="CSV delimiter.")
    date_column: Annotated[NonEmptyStr, Profile.USER] = Field(
        default="date", description="Name of the CSV column that holds the dates."
    )
    date_format: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Optional datetime format passed to pandas.to_datetime.",
    )
    value_column: Annotated[NonEmptyStr, Profile.USER] = Field(
        default="value", description="Name of the CSV column that holds the values."
    )
    aggregate: Annotated[FlowTimeAggregate, Profile.DEV] = Field(
        default="mean",
        description="Stress-period aggregation method.",
    )
    units: Annotated[str | None, Profile.USER] = Field(default=None, description=_UNITS_DESCRIPTION)


class ForcingSegment(HydroModelBase):
    """One dated segment of a piecewise forcing, a constant or a csv."""

    start: Annotated[str, Profile.USER] = Field(
        ...,
        description="Inclusive segment start date (ISO date or datetime string).",
        examples=["2020-01-01"],
    )
    end: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Exclusive segment end date (ISO string); None extends to the simulation end."
        ),
    )
    forcing: Annotated[ConstantForcing | CsvForcing, Profile.USER] = Field(
        ...,
        discriminator="kind",
        description="What this segment reads, a constant or a csv.",
    )

    @field_validator("start", "end", mode="after")
    @classmethod
    def _validate_dates(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            pd.Timestamp(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"piecewise segment date '{value}' is not a valid timestamp") from exc
        return value


class PiecewiseForcing(HydroModelBase):
    """Ordered dated segments, each a constant or a csv."""

    kind: Annotated[Literal["piecewise"], Profile.USER] = Field(
        default="piecewise",
        description="This forcing is a list of dated segments.",
    )
    segments: Annotated[list[ForcingSegment], Profile.USER] = Field(
        ...,
        min_length=1,
        description="Date-ordered segments covering the simulation window.",
    )
    units: Annotated[str | None, Profile.USER] = Field(default=None, description=_UNITS_DESCRIPTION)

    @model_validator(mode="after")
    def _validate_segment_order(self) -> PiecewiseForcing:
        """Require strictly date-ordered segments with non-overlapping windows."""
        previous_start: pd.Timestamp | None = None
        previous_end: pd.Timestamp | None = None
        for index, segment in enumerate(self.segments):
            start = pd.Timestamp(segment.start)
            end = pd.Timestamp(segment.end) if segment.end is not None else None
            if end is not None and end <= start:
                raise ValueError(f"piecewise segment[{index}] end must be strictly after its start")
            if previous_start is not None and start <= previous_start:
                raise ValueError(
                    f"piecewise segment[{index}] start must be after the previous segment start"
                )
            if previous_end is not None and start < previous_end:
                raise ValueError(
                    f"piecewise segment[{index}] start must not precede the previous segment end"
                )
            previous_start = start
            previous_end = end
        return self


class SeasonalForcing(HydroModelBase):
    """Calendar month or season to value, repeated across the years."""

    kind: Annotated[Literal["seasonal"], Profile.USER] = Field(
        default="seasonal",
        description="This forcing repeats one value per month or per season every year.",
    )
    by_month: Annotated[dict[int, float] | None, Profile.USER] = Field(
        default=None,
        description="Mapping of calendar month (1-12) to a forcing value.",
    )
    by_season: Annotated[dict[str, float] | None, Profile.USER] = Field(
        default=None,
        description="Mapping of meteorological season (DJF/MAM/JJA/SON) to a forcing value.",
    )
    units: Annotated[str | None, Profile.USER] = Field(default=None, description=_UNITS_DESCRIPTION)

    @model_validator(mode="after")
    def _validate_one_complete_mapping(self) -> SeasonalForcing:
        """Require exactly one of by_month/by_season, fully populated."""
        if (self.by_month is None) == (self.by_season is None):
            raise ValueError("seasonal forcing requires exactly one of by_month or by_season")
        if self.by_month is not None:
            missing = sorted(set(range(1, 13)) - set(self.by_month))
            if missing:
                raise ValueError(f"seasonal by_month is missing months {missing}")
            extra = sorted(month for month in self.by_month if month < 1 or month > 12)
            if extra:
                raise ValueError(f"seasonal by_month has invalid months {extra}")
        else:
            assert self.by_season is not None
            seasons = {"DJF", "MAM", "JJA", "SON"}
            missing_seasons = sorted(seasons - set(self.by_season))
            if missing_seasons:
                raise ValueError(f"seasonal by_season is missing seasons {missing_seasons}")
            extra_seasons = sorted(set(self.by_season) - seasons)
            if extra_seasons:
                raise ValueError(f"seasonal by_season has invalid seasons {extra_seasons}")
        return self


TimeSeriesForcing = Annotated[
    ConstantForcing | CsvForcing | PiecewiseForcing | SeasonalForcing,
    Field(
        discriminator="kind",
        description=(
            "A quantity over the stress periods: 'constant', 'csv', 'piecewise' or 'seasonal'."
        ),
    ),
]
"""The one shape of a quantity that varies over the stress periods."""


def carries_a_unit(value: object) -> bool:
    """Return True for a text value with a unit, such as '2 mm/day'."""
    if not isinstance(value, str):
        return False
    try:
        float(value)
    except ValueError:
        return True
    return False


@dataclass(frozen=True)
class _Reading:
    """How a mount reads the values of a forcing."""

    si_unit: str
    quantity: TypeAdapter[float]
    normalize: Callable[[str], str]
    refuses: str | None = None
    """Raised when ``units`` is not of this quantity, or None to leave it to the runtime."""

    def checked_units(self, units: str | None) -> str | None:
        if units is None or self.refuses is None:
            return units
        try:
            self.normalize(units)
        except ValueError as exc:
            raise ValueError(self.refuses.format(units=units)) from exc
        return units

    def constant(self, forcing: ConstantForcing) -> ConstantForcing:
        """Return a constant with its value in a number, in SI when it carried its unit."""
        if not isinstance(forcing.value, str):
            self.checked_units(forcing.units)
            return forcing
        if not carries_a_unit(forcing.value):
            raise ValueError(
                f"value = {forcing.value!r} is a number written as a text. Write it as a "
                "number, or add its unit."
            )
        if forcing.units is not None:
            raise ValueError(
                f"value = {forcing.value!r} carries its own unit and units = "
                f"{forcing.units!r} names another. Write the unit once: in value, or as a "
                "bare number in value with the unit in units."
            )
        return forcing.model_copy(
            update={
                "value": self.quantity.validate_python(forcing.value),
                "units": self.si_unit,
            }
        )

    def piecewise(self, forcing: PiecewiseForcing) -> PiecewiseForcing:
        """Return a piecewise forcing with one unit, the one a run converts every segment with.

        A unit written on a segment and not on the forcing would be ignored, so a
        segment that names another unit is refused. When only the segments name a
        unit, and they agree, it becomes the unit of the forcing.
        """
        segments = [
            segment.model_copy(update={"forcing": self.of(segment.forcing)})
            for segment in forcing.segments
        ]
        self.checked_units(forcing.units)
        declared = {
            self.normalize(str(segment.forcing.units))
            for segment in segments
            if segment.forcing.units is not None
        }
        update: dict[str, object] = {"segments": segments}
        if forcing.units is not None:
            own = self.normalize(str(forcing.units))
            other = sorted(unit for unit in declared if unit != own)
            if other:
                raise ValueError(
                    f"piecewise segments name the unit {other[0]!r} and the forcing names "
                    f"units = {forcing.units!r}. Write units once, on the piecewise forcing."
                )
        elif len(declared) > 1:
            raise ValueError(
                f"piecewise segments name several units ({', '.join(sorted(declared))}). "
                "Write units once, on the piecewise forcing."
            )
        elif declared:
            update["units"] = declared.pop()
        return forcing.model_copy(update=update)

    def of(self, forcing: object) -> object:
        """Return *forcing* as this mount reads it."""
        if isinstance(forcing, ConstantForcing):
            return self.constant(forcing)
        if isinstance(forcing, PiecewiseForcing):
            return self.piecewise(forcing)
        if isinstance(forcing, CsvForcing | SeasonalForcing):
            self.checked_units(forcing.units)
        return forcing


def declared_forcing_values(forcing: object) -> list[float]:
    """Return the values a forcing declares in the file, before any CSV is read."""
    if isinstance(forcing, ConstantForcing):
        return [float(forcing.value)]
    if isinstance(forcing, SeasonalForcing):
        mapping = forcing.by_month or forcing.by_season or {}
        return [float(value) for value in mapping.values()]
    if isinstance(forcing, PiecewiseForcing):
        return [
            value
            for segment in forcing.segments
            for value in declared_forcing_values(segment.forcing)
        ]
    return []


_VOLUME_RATE = _Reading("m3/s", TypeAdapter(VolumetricFlowM3PerSecond), normalize_m3_per_s_unit)
_SURFACE_RATE = _Reading(
    "m/s",
    TypeAdapter(FluxDensityMPerS),
    normalize_m_per_s_unit,
    refuses=(
        "units = {units!r} is not a rate per unit of surface. Write a length per time, one "
        f"of: {', '.join(M_PER_S_CANONICAL_UNITS)}."
    ),
)
_HEAD = _Reading("m", TypeAdapter(LengthMeters), normalize_length_unit)

VolumeRateForcing = Annotated[TimeSeriesForcing, AfterValidator(_VOLUME_RATE.of)]
"""A forcing read as a volume per time, m3/s when it names no unit."""

SurfaceRateForcing = Annotated[TimeSeriesForcing, AfterValidator(_SURFACE_RATE.of)]
"""A forcing read as a length per time, m/s when it names no unit."""

HeadForcing = Annotated[TimeSeriesForcing, AfterValidator(_HEAD.of)]
"""A forcing read as a length, meters when it names no unit."""


__all__ = [
    "ConstantForcing",
    "CsvForcing",
    "FlowTimeAggregate",
    "ForcingSegment",
    "HeadForcing",
    "PiecewiseForcing",
    "SeasonalForcing",
    "SurfaceRateForcing",
    "TimeSeriesForcing",
    "VolumeRateForcing",
    "carries_a_unit",
    "declared_forcing_values",
]
