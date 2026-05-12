"""Pumping/injection well payloads for the flow process.

Defines :class:`FlowWellConfig` and the runtime forcing variants
(:class:`FlowWellForcingConstantConfig`, :class:`FlowWellForcingCsvConfig`)
unified as the discriminated union :data:`FlowWellForcingConfig`.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from numbers import Real
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import NonEmptyStr
from hydromodpy.core.units import FlowRate
from hydromodpy.core.units.volumetric_flow import normalize_m3_per_s_unit
from hydromodpy.physics.base.forcing import FlowTimeAggregate, FlowTimeFillMethod

if TYPE_CHECKING:
    from hydromodpy.core.grid_reference import GridReference


class FlowWellForcingConstantConfig(HydroModelBase):
    """One constant well-rate forcing applied to every stress period."""

    kind: Annotated[Literal["constant"], Profile.USER] = Field(
        default="constant",
        description="Discriminator tag for the constant well-forcing variant.",
    )
    value: Annotated[FlowRate, Profile.USER] = Field(
        ...,
        description="Constant well rate in the same units as the parent well.",
    )
    units: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Source units of the constant value before runtime conversion.",
    )


class FlowWellForcingCsvConfig(HydroModelBase):
    """CSV-backed well forcing resolved at runtime against simulation.time."""

    kind: Annotated[Literal["csv"], Profile.USER] = Field(
        default="csv",
        description="Discriminator tag for the CSV-backed well-forcing variant.",
    )
    path_file: Annotated[Path, Profile.DEV] = Field(
        ..., description="Path to the CSV chronicle file."
    )
    sep: Annotated[NonEmptyStr, Profile.DEV] = Field(default=",", description="CSV delimiter.")
    date_column: Annotated[NonEmptyStr, Profile.DEV] = Field(
        default="date", description="CSV column containing timestamps."
    )
    date_format: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Optional datetime format passed to pandas.to_datetime.",
    )
    value_column: Annotated[NonEmptyStr, Profile.DEV] = Field(
        default="value", description="CSV column containing well rates."
    )
    fill_method: Annotated[FlowTimeFillMethod, Profile.DEV] = Field(
        default="ffill",
        description="Gap-filling policy used when a stress period has no direct sample.",
    )
    aggregate: Annotated[FlowTimeAggregate, Profile.DEV] = Field(
        default="mean",
        description="Stress-period aggregation method.",
    )
    units: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Source units of CSV values before runtime conversion.",
    )


FlowWellForcingConfig = Annotated[
    FlowWellForcingConstantConfig | FlowWellForcingCsvConfig,
    Field(
        discriminator="kind",
        description="Discriminated union of well-forcing payloads (constant or csv).",
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
        description="Direct cell indices as [lay, row, col] (0-based, FLOPY convention).",
    )

    @field_validator("cell", mode="before")
    @classmethod
    def _validate_cell(cls, value):
        return _coerce_cell_indices(value)


class FlowWellLocationAbsoluteXY(HydroModelBase):
    """Projected ``(x, y)`` coordinates in solver units."""

    kind: Annotated[Literal["absolute_xy"], Profile.USER] = Field(
        default="absolute_xy",
        description="Discriminator tag for the absolute-xy well location.",
    )
    layer: Annotated[int, Profile.DEV] = Field(
        default=0,
        description="Layer index (0-based) targeted by the well.",
    )
    x: Annotated[float, Profile.USER] = Field(
        ..., description="Projected X coordinate in solver units."
    )
    y: Annotated[float, Profile.USER] = Field(
        ..., description="Projected Y coordinate in solver units."
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
    layer: Annotated[int, Profile.DEV] = Field(
        default=0,
        description="Layer index (0-based) targeted by the well.",
    )
    x_rel: Annotated[float, Profile.USER] = Field(
        ...,
        description="Relative X position in [0, 1] from west to east.",
    )
    y_rel: Annotated[float, Profile.USER] = Field(
        ...,
        description="Relative Y position in [0, 1] from south to north.",
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
    )
    forcing: Annotated[FlowWellForcingConfig | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional runtime forcing declaration. Supported modes: "
            "'constant' and 'csv'. The launcher resolves this payload to "
            "well.flux using [simulation.time]."
        ),
    )
    units: Annotated[str, Profile.DEV] = Field(default="m3/s", description="Units of flux values.")
    description: Annotated[str, Profile.USER] = Field(
        default="", description="Optional well description."
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
                        raise ValueError("well.units conflicts with well.forcing.units")
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
