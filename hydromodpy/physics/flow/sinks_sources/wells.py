"""Pumping/injection well payloads for the flow process."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite
from numbers import Real
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units.volumetric_flow import normalize_m3_per_s_unit
from hydromodpy.physics.base.forcing import VolumeRateForcing

if TYPE_CHECKING:
    from hydromodpy.core.grid_reference import GridReference


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
        json_schema_extra=field_metadata(unit="-"),
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
    layer: Annotated[int | None, Profile.USER] = Field(
        default=None,
        description=(
            "Model layer the point lies in, counted from 0 at the top. Left out, the "
            "well takes the top active cell of its column."
        ),
        json_schema_extra={"unit": "-"},
    )
    x: Annotated[float, Profile.USER] = Field(
        ...,
        description="Easting of the point in the projected CRS of the project, in meters.",
        examples=[352400.0],
        json_schema_extra={"unit": "m"},
    )
    y: Annotated[float, Profile.USER] = Field(
        ...,
        description="Northing of the point in the projected CRS of the project, in meters.",
        examples=[6788300.0],
        json_schema_extra={"unit": "m"},
    )

    @field_validator("layer", mode="before")
    @classmethod
    def _validate_layer(cls, value):
        return None if value is None else _coerce_layer(value)

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
    layer: Annotated[int | None, Profile.USER] = Field(
        default=None,
        description=(
            "Model layer the point lies in, counted from 0 at the top. Left out, the "
            "well takes the top active cell of its column."
        ),
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
        return None if value is None else _coerce_layer(value)

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

    enabled: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Whether this well pumps or injects. Declaring it is what activates it. false keeps the table "
            "and builds nothing from it."
        ),
    )
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
            "Well rate, in the unit that units names (m3/s by default). One number for a "
            "constant rate, or one per stress period. It follows the sign of MODFLOW: "
            "negative when the well pumps, positive when it injects."
        ),
        # A pumping rate is negative, so a log transform is not available to it.
        json_schema_extra=field_metadata(calibrable=Calibrable(units="m3/s", unit_field="units")),
    )
    forcing: Annotated[VolumeRateForcing | None, Profile.USER] = Field(
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

    def resolve_cell(self, grid: GridReference) -> tuple[int | None, int, int]:
        """Resolve this well location against one solver grid.

        The layer is ``None`` when the location names none: the caller places
        the well on the top active cell of the column.
        """
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
        layer = None if location.layer is None else int(location.layer)
        return (layer, row, col)


WELL_THROTTLE_WARNING_FRACTION = 0.1
"""Share of a requested pumping volume above which a cut is reported."""

WELLS_PUMPED_METRIC = "wells_pumped_percent"
"""Metric a solver writes: the share of the requested pumping that was applied, in percent."""

WELLS_PUMPED_CHECK = "wells_pumped"
"""Name of the validity of the seal that says whether the wells pumped what was asked."""


def pumped_percent(
    requested: Mapping[object, float],
    applied: Mapping[object, float],
) -> float | None:
    """Return the share of the requested volume that was applied, in percent.

    Both mappings give a volume in m3 per well cell, the sign ignored. The
    share is taken over all the wells together. ``None`` when nothing was
    requested.
    """
    wanted = sum(abs(float(v)) for v in requested.values())
    if wanted <= 0.0:
        return None
    got = sum(abs(float(applied.get(cell, 0.0))) for cell in requested)
    return 100.0 * got / wanted


def throttled_well_report(
    requested: Mapping[object, float],
    applied: Mapping[object, float],
    *,
    threshold: float = WELL_THROTTLE_WARNING_FRACTION,
) -> list[dict[str, float | object]]:
    """List the wells whose applied volume falls short of the requested one.

    ``requested`` and ``applied`` map a well cell to a volume in m3 (pumping is
    negative, the sign is ignored). MODFLOW 6 ``AUTO_FLOW_REDUCE`` cuts the
    extraction of a well whose cell is nearly dry, and the budget only
    publishes what was applied. A well is reported when the cut exceeds
    ``threshold`` of what was requested. Each row holds ``cell``,
    ``requested``, ``applied`` and ``cut_fraction``.
    """
    rows: list[dict[str, float | object]] = []
    for cell, wanted in requested.items():
        wanted_abs = abs(float(wanted))
        if wanted_abs <= 0.0:
            continue
        got_abs = abs(float(applied.get(cell, 0.0)))
        cut = max(0.0, 1.0 - got_abs / wanted_abs)
        if cut > float(threshold):
            rows.append(
                {
                    "cell": cell,
                    "requested": wanted_abs,
                    "applied": got_abs,
                    "cut_fraction": cut,
                }
            )
    return rows


def throttled_well_message(rows: Sequence[Mapping[str, object]]) -> str:
    """Return the warning that names the wells AUTO_FLOW_REDUCE throttled."""
    parts = [
        f"cell {row['cell']}: {float(row['applied']):.6g} of {float(row['requested']):.6g} m3 "  # type: ignore[arg-type]
        f"({100.0 * (1.0 - float(row['cut_fraction'])):.0f} % pumped)"  # type: ignore[arg-type]
        for row in rows
    ]
    return (
        "MODFLOW 6 AUTO_FLOW_REDUCE cut the pumping of "
        f"{len(rows)} well cell(s) by more than "
        f"{100.0 * WELL_THROTTLE_WARNING_FRACTION:.0f} %: "
        + "; ".join(parts)
        + ". The cell is nearly dry. Put the well in a deeper layer or lower its rate."
    )
