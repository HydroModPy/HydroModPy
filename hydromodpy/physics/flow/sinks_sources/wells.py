"""Pumping/injection well payloads for the flow process.

Defines :class:`FlowWellConfig` and the runtime forcing variants
(:class:`FlowWellForcingConstantConfig`, :class:`FlowWellForcingCsvConfig`,
:class:`FlowWellForcingPiecewiseConfig`, :class:`FlowWellForcingSeasonalConfig`)
unified as the discriminated union :data:`FlowWellForcingConfig`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from math import isfinite
from numbers import Real
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Literal, TypeAlias

import pandas as pd
from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import NonEmptyStr
from hydromodpy.core.tracking import InputFile
from hydromodpy.core.units import FlowRate
from hydromodpy.core.units.volumetric_flow import normalize_m3_per_s_unit
from hydromodpy.physics.base.forcing import FlowTimeAggregate

if TYPE_CHECKING:
    from hydromodpy.core.grid_reference import GridReference


def _carries_a_unit(value: object) -> bool:
    """Return True for a text value with a unit, such as '2 mm/day'."""
    if not isinstance(value, str):
        return False
    try:
        float(value)
    except ValueError:
        return True
    return False


class FlowWellForcingConstantConfig(HydroModelBase):
    """One constant well-rate forcing applied to every stress period."""

    forcing_si_unit: ClassVar[str] = "m3/s"
    """Unit the value is stored in once it is validated."""

    kind: Annotated[Literal["constant"], Profile.USER] = Field(
        default="constant",
        description="Discriminator tag for the constant well-forcing variant.",
    )
    value: Annotated[FlowRate, Profile.USER] = Field(
        ...,
        description=(
            "Value applied to every stress period, in the unit that units names. For a "
            "well, a negative rate pumps and a positive one injects."
        ),
    )
    units: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Unit of the forcing values: a volume per time such as 'm3/day', or a rate "
            "such as 'mm/day' for a lake rainfall. Values are converted to SI when the run "
            "starts. Unset, a well forcing takes the well's units, other forcings read SI."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _take_the_unit_of_the_value(cls, data: Any) -> Any:
        """Store a value written with its unit in SI, and say so in units.

        The value is converted when it is read, so units must then name the SI
        unit: a run applies units to the stored number. A units key beside a
        value that carries its own unit is refused, since one of the two would
        be applied twice.
        """
        if not isinstance(data, Mapping) or not _carries_a_unit(data.get("value")):
            return data
        if data.get("units") is not None:
            raise ValueError(
                f"value = {data['value']!r} carries its own unit and units = "
                f"{data['units']!r} names another. Write the unit once: in value, or "
                "as a bare number in value with the unit in units."
            )
        return {**data, "units": cls.forcing_si_unit}


class FlowWellForcingCsvConfig(HydroModelBase):
    """CSV-backed well forcing resolved at runtime against simulation.time."""

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "fill_method": (
            "no step reads it. A stress period with no sample takes the sample in force, "
            "and simulation.time.coverage_policy decides what happens before or after the "
            "record."
        ),
    }

    kind: Annotated[Literal["csv"], Profile.USER] = Field(
        default="csv",
        description="Discriminator tag for the CSV-backed well-forcing variant.",
    )
    path_file: Annotated[
        Path,
        Profile.USER,
        InputFile(role="wells", category="data"),
    ] = Field(
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
    units: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Unit of the forcing values: a volume per time such as 'm3/day', or a rate "
            "such as 'mm/day' for a lake rainfall. Values are converted to SI when the run "
            "starts. Unset, a well forcing takes the well's units, other forcings read SI."
        ),
    )


FlowWellForcingSubConfig: TypeAlias = Annotated[
    FlowWellForcingConstantConfig | FlowWellForcingCsvConfig,
    Field(
        discriminator="kind",
        description="Constant or csv sub-forcing nested inside one piecewise segment.",
    ),
]
"""Discriminated sub-forcing allowed inside a piecewise segment (constant or csv)."""


class FlowWellForcingSegment(HydroModelBase):
    """One dated segment of a piecewise forcing carrying a constant or csv sub-forcing."""

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
    forcing: Annotated[FlowWellForcingSubConfig, Profile.USER] = Field(
        ...,
        description="Sub-forcing for this segment, discriminated by 'kind' (constant or csv).",
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


class FlowWellForcingPiecewiseConfig(HydroModelBase):
    """Ordered dated segments, each resolved by its constant or csv sub-forcing."""

    kind: Annotated[Literal["piecewise"], Profile.USER] = Field(
        default="piecewise",
        description="Discriminator tag for the piecewise well-forcing variant.",
    )
    segments: Annotated[list[FlowWellForcingSegment], Profile.USER] = Field(
        ...,
        min_length=1,
        description="Date-ordered segments covering the simulation window.",
    )
    units: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Unit of the forcing values: a volume per time such as 'm3/day', or a rate "
            "such as 'mm/day' for a lake rainfall. Values are converted to SI when the run "
            "starts. Unset, a well forcing takes the well's units, other forcings read SI."
        ),
    )

    forcing_unit_normalizer: ClassVar[Callable[[str], str]] = staticmethod(normalize_m3_per_s_unit)
    """Canonical form of a unit of this forcing family."""

    @model_validator(mode="after")
    def _one_unit_for_every_segment(self) -> FlowWellForcingPiecewiseConfig:
        """Refuse segments whose unit differs from the one of the forcing.

        A run converts every segment with the units of the piecewise forcing,
        so a unit written on a segment would otherwise be ignored. When only
        the segments name a unit, and they agree, it becomes the unit of the
        forcing.
        """
        normalize = type(self).forcing_unit_normalizer
        declared = {
            normalize(str(segment.forcing.units))
            for segment in self.segments
            if "units" in segment.forcing.model_fields_set and segment.forcing.units is not None
        }
        if not declared:
            return self
        if self.units is not None:
            own = normalize(str(self.units))
            other = sorted(unit for unit in declared if unit != own)
            if other:
                raise ValueError(
                    f"piecewise segments name the unit {other[0]!r} and the forcing names "
                    f"units = {self.units!r}. Write units once, on the piecewise forcing."
                )
            return self
        if len(declared) > 1:
            raise ValueError(
                f"piecewise segments name several units ({', '.join(sorted(declared))}). "
                "Write units once, on the piecewise forcing."
            )
        # Assigned through __dict__: validate_assignment would run this validator again.
        self.__dict__["units"] = declared.pop()
        self.__pydantic_fields_set__.add("units")
        return self

    @model_validator(mode="after")
    def _validate_segment_order(self) -> FlowWellForcingPiecewiseConfig:
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


class FlowWellForcingSeasonalConfig(HydroModelBase):
    """Calendar month-to-value (or season-to-value) mapping repeated across years."""

    kind: Annotated[Literal["seasonal"], Profile.USER] = Field(
        default="seasonal",
        description="Discriminator tag for the seasonal well-forcing variant.",
    )
    by_month: Annotated[dict[int, float] | None, Profile.USER] = Field(
        default=None,
        description="Mapping of calendar month (1-12) to a forcing value.",
    )
    by_season: Annotated[dict[str, float] | None, Profile.USER] = Field(
        default=None,
        description="Mapping of meteorological season (DJF/MAM/JJA/SON) to a forcing value.",
    )
    units: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Unit of the forcing values: a volume per time such as 'm3/day', or a rate "
            "such as 'mm/day' for a lake rainfall. Values are converted to SI when the run "
            "starts. Unset, a well forcing takes the well's units, other forcings read SI."
        ),
    )

    @model_validator(mode="after")
    def _validate_one_complete_mapping(self) -> FlowWellForcingSeasonalConfig:
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


FlowWellForcingConfig = Annotated[
    FlowWellForcingConstantConfig
    | FlowWellForcingCsvConfig
    | FlowWellForcingPiecewiseConfig
    | FlowWellForcingSeasonalConfig,
    Field(
        discriminator="kind",
        description=(
            "Discriminated union of well-forcing payloads (constant, csv, piecewise, or seasonal)."
        ),
    ),
]
"""Discriminated union of well-forcing payloads."""


def _coerce_cell_indices(value: Any) -> tuple[int, int, int]:
    """Normalize a ``cell`` payload into a strict ``(lay, row, col)`` tuple."""
    if isinstance(value, Mapping):
        try:
            raw_seq = [value["lay"], value["row"], value["col"]]
        except KeyError as exc:
            raise ValueError("well.cell mapping must define lay, row, and col") from exc
    elif isinstance(value, (list, tuple)):
        raw_seq = list(value)
    else:
        raise TypeError("well.cell must be a mapping or a 3-item list [lay, row, col]")

    if len(raw_seq) != 3:
        raise ValueError("well.cell must contain exactly 3 values: [lay, row, col]")

    parsed: list[int] = []
    for axis, raw_item in zip(("lay", "row", "col"), raw_seq, strict=False):
        if isinstance(raw_item, bool):
            raise TypeError(f"well.cell.{axis} must be an integer")
        if isinstance(raw_item, Real):
            numeric = float(raw_item)
            if not numeric.is_integer():
                raise TypeError(f"well.cell.{axis} must be an integer")
            index_value = int(numeric)
        else:
            raise TypeError(f"well.cell.{axis} must be an integer")
        if index_value < 0:
            raise ValueError(f"well.cell.{axis} must be >= 0")
        parsed.append(index_value)
    return tuple(parsed)


def _coerce_layer(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError("well.layer must be an integer")
    numeric = float(value)
    if not numeric.is_integer():
        raise TypeError("well.layer must be an integer")
    layer = int(numeric)
    if layer < 0:
        raise ValueError("well.layer must be >= 0")
    return layer


def _coerce_absolute_coordinate(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError("well absolute coordinates must be numeric")
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError("well absolute coordinates must be finite")
    return numeric


def _coerce_relative_coordinate(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError("well relative coordinates must be numeric")
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError("well relative coordinates must be finite")
    if numeric < 0.0 or numeric > 1.0:
        raise ValueError("well relative coordinates must be within [0, 1]")
    return numeric


class FlowWellLocationCell(HydroModelBase):
    """Direct ``[lay, row, col]`` addressing on a structured solver grid."""

    kind: Annotated[Literal["cell"], Profile.USER] = Field(
        default="cell",
        description="Discriminator tag for the cell-based well location.",
    )
    cell: Annotated[tuple[int, int, int], Profile.USER] = Field(
        ...,
        description=(
            "Cell indices as [layer, row, column], counted from 0. Only a structured grid "
            "has rows and columns."
        ),
        examples=[[0, 10, 12]],
    )

    @field_validator("cell", mode="before")
    @classmethod
    def _validate_cell(cls, value):
        return _coerce_cell_indices(value)


class FlowWellLocationAbsoluteXY(HydroModelBase):
    """Projected ``(x, y)`` coordinates in the project CRS."""

    kind: Annotated[Literal["absolute_xy"], Profile.USER] = Field(
        default="absolute_xy",
        description="Discriminator tag for the absolute-xy well location.",
    )
    layer: Annotated[int, Profile.USER] = Field(
        default=0,
        description="Model layer the point lies in, counted from 0 at the top.",
        json_schema_extra={"unit": "-"},
    )
    x: Annotated[float, Profile.USER] = Field(
        ...,
        description="Easting of the point in the projected CRS of the project, in metres.",
        examples=[352400.0],
        json_schema_extra={"unit": "m"},
    )
    y: Annotated[float, Profile.USER] = Field(
        ...,
        description="Northing of the point in the projected CRS of the project, in metres.",
        examples=[6788300.0],
        json_schema_extra={"unit": "m"},
    )

    @field_validator("layer", mode="before")
    @classmethod
    def _validate_layer(cls, value):
        return _coerce_layer(value)

    @field_validator("x", "y", mode="before")
    @classmethod
    def _validate_coordinate(cls, value):
        return _coerce_absolute_coordinate(value)


class FlowWellLocationRelativeXY(HydroModelBase):
    """Normalized ``(x_rel, y_rel)`` in ``[0, 1]`` over the domain extent."""

    kind: Annotated[Literal["relative_xy"], Profile.USER] = Field(
        default="relative_xy",
        description="Discriminator tag for the relative-xy well location.",
    )
    layer: Annotated[int, Profile.USER] = Field(
        default=0,
        description="Model layer the point lies in, counted from 0 at the top.",
        json_schema_extra={"unit": "-"},
    )
    x_rel: Annotated[float, Profile.USER] = Field(
        ...,
        description=(
            "Position across the model extent from west (0) to east (1). A share of the "
            "extent, so it has no unit."
        ),
        examples=[0.5],
        json_schema_extra={"unit": "-"},
    )
    y_rel: Annotated[float, Profile.USER] = Field(
        ...,
        description=(
            "Position across the model extent from south (0) to north (1). A share of the "
            "extent, so it has no unit."
        ),
        examples=[0.5],
        json_schema_extra={"unit": "-"},
    )

    @field_validator("layer", mode="before")
    @classmethod
    def _validate_layer(cls, value):
        return _coerce_layer(value)

    @field_validator("x_rel", "y_rel", mode="before")
    @classmethod
    def _validate_coordinate(cls, value):
        return _coerce_relative_coordinate(value)


FlowWellLocation: TypeAlias = Annotated[
    FlowWellLocationCell | FlowWellLocationAbsoluteXY | FlowWellLocationRelativeXY,
    Field(
        discriminator="kind",
        description=(
            "Discriminated union of well-location payloads (cell, absolute_xy, or relative_xy)."
        ),
    ),
]
"""Discriminated union of well-location payloads."""


class FlowWellConfig(HydroModelBase):
    """
    Typed payload for one pumping or injection well.

    A well is defined by its location (``location``) and its flux schedule
    over time (``flux``). ``location`` is a discriminated union with three
    variants: ``cell`` for direct ``[lay, row, col]`` indexing, ``absolute_xy``
    for projected coordinates, or ``relative_xy`` for normalized horizontal
    coordinates. ``flux`` follows the MODFLOW sign convention: negative =
    pumping, positive = injection. ``flux`` may be a scalar (constant rate)
    or a list with one value per stress period.
    """

    location: Annotated[FlowWellLocation, Profile.USER] = Field(
        ...,
        description=(
            "Well location payload. Discriminated by 'kind': 'cell', "
            "'absolute_xy', or 'relative_xy'."
        ),
    )
    flux: Annotated[float | list[float] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Well rate [L^3/T]. Scalar for constant rate, or one value per stress period. "
            "Negative = pumping, positive = injection."
        ),
        # A pumping rate is negative, so a log transform is not available to it.
        json_schema_extra=field_metadata(calibrable=Calibrable(units="m3/s")),
    )
    forcing: Annotated[FlowWellForcingConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Rate schedule that replaces flux: 'constant', 'csv', 'piecewise' or "
            "'seasonal'. It is turned into one rate per stress period of "
            "[simulation.time]. A well takes flux or forcing, never both."
        ),
    )
    units: Annotated[str, Profile.USER] = Field(
        default="m3/s",
        description=(
            "Unit of flux, or of the forcing values: a volume per time such as "
            "'m3/day', 'm3/h' or 'l/s'. The rates are converted to m3/s when the run starts."
        ),
        examples=["m3/day"],
    )
    description: Annotated[str, Profile.USER] = Field(
        default="",
        description="Free text about the well, kept with the configuration and not read by the model.",
    )

    @field_validator("flux", mode="before")
    @classmethod
    def _validate_flux(cls, value):
        if value is None:
            return None
        if isinstance(value, bool):
            raise TypeError("well.flux must be numeric or a list of numeric values")
        if isinstance(value, Real):
            numeric = float(value)
            if not isfinite(numeric):
                raise ValueError("well.flux must contain only finite values")
            return numeric
        if isinstance(value, (list, tuple)):
            if len(value) == 0:
                raise ValueError("well.flux list cannot be empty")
            parsed: list[float] = []
            for idx, raw_item in enumerate(value):
                if isinstance(raw_item, bool) or not isinstance(raw_item, Real):
                    raise TypeError(f"well.flux[{idx}] must be numeric")
                numeric = float(raw_item)
                if not isfinite(numeric):
                    raise ValueError("well.flux must contain only finite values")
                parsed.append(numeric)
            return parsed
        raise TypeError("well.flux must be numeric or a list of numeric values")

    @model_validator(mode="after")
    def _validate_flux_and_forcing(self):
        """Enforce one consistent flux/forcing/units payload."""
        if self.flux is None and self.forcing is None:
            raise ValueError("well requires either flux or forcing")
        if self.flux is not None and self.forcing is not None:
            raise ValueError("well.flux and well.forcing are mutually exclusive")
        if self.forcing is not None:
            parent_units = str(self.units).strip() or "m3/s"
            forcing_units = getattr(self.forcing, "units", None)
            parent_units_explicit = "units" in self.model_fields_set
            forcing_units_explicit = "units" in self.forcing.model_fields_set
            if forcing_units_explicit:
                normalized_forcing_units = normalize_m3_per_s_unit(
                    str(forcing_units).strip() or "m3/s"
                )
                if parent_units_explicit:
                    normalized_parent_units = normalize_m3_per_s_unit(parent_units)
                    if (
                        normalized_parent_units != "m3/s"
                        and normalized_parent_units != normalized_forcing_units
                    ):
                        raise ValueError(
                            f"well units = {parent_units!r} and its forcing names the unit "
                            f"{normalized_forcing_units!r}. Write the unit once: on the well, "
                            "or on the forcing. A value written with its unit, such as "
                            "'100 m**3/day', names the unit of the forcing."
                        )
            else:
                normalized_forcing_units = normalize_m3_per_s_unit(parent_units)
            if forcing_units != normalized_forcing_units:
                self.forcing = self.forcing.model_copy(update={"units": normalized_forcing_units})
            if self.units != "m3/s":
                self.units = "m3/s"

        return self

    def resolve_cell(self, grid: GridReference) -> tuple[int, int, int]:
        """Resolve this well location against one solver grid."""
        location = self.location
        if isinstance(location, FlowWellLocationCell):
            return location.cell

        if isinstance(location, FlowWellLocationAbsoluteXY):
            x = float(location.x)
            y = float(location.y)
        elif isinstance(location, FlowWellLocationRelativeXY):
            x = float(grid.xmin) + float(location.x_rel) * (float(grid.xmax) - float(grid.xmin))
            y = float(grid.ymin) + float(location.y_rel) * (float(grid.ymax) - float(grid.ymin))
        else:
            raise ValueError("well location cannot be resolved without cell or coordinate mode")

        xmin = float(grid.xmin)
        xmax = float(grid.xmax)
        ymin = float(grid.ymin)
        ymax = float(grid.ymax)
        if x < xmin or x > xmax or y < ymin or y > ymax:
            raise ValueError(
                "well coordinates are outside the structured solver grid extent "
                f"[{xmin}, {xmax}] x [{ymin}, {ymax}]."
            )
        col = int((x - xmin) / float(grid.dx))
        row = int((ymax - y) / float(grid.dy))
        if col == int(grid.ncol) and x == xmax:
            col = int(grid.ncol) - 1
        if row == int(grid.nrow) and y == ymin:
            row = int(grid.nrow) - 1
        if col < 0 or col >= int(grid.ncol) or row < 0 or row >= int(grid.nrow):
            raise ValueError("well coordinates could not be resolved to a structured grid cell.")
        return (int(location.layer), row, col)
