"""The calibration outputs: point, boundary, cell and lake records and the output union."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, ClassVar, Literal, TypeAlias

from pydantic import (
    Field,
    TypeAdapter,
    model_validator,
)

from hydromodpy.calibration.config_network import CalibOutputNetwork
from hydromodpy.calibration.config_terms import OUTPUT_REDUCER_VALUE_DOCS, OutputReducer, OutputTime
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.said import say
from hydromodpy.core.config_kit.types import (
    NonNegativeInt,
    StationName,
)
from hydromodpy.core.units.types import Length


class ScoresAnObservedRecord:
    """Shared observation surface for the outputs that carry a time axis.

    An output says what it is compared against in one of two ways, never both:
    ``observes`` names a station whose loaded record is aligned on the simulated
    timestamps, and ``observed_values`` is a positional vector written into the
    file. A network output inherits neither: its criterion balances two
    simulated quantities and has no record to fit.
    """

    observes: Annotated[StationName | None, Profile.USER] = Field(
        default=None,
        description="Station whose loaded record this output is scored against. The "
        "record is aligned on the simulated timestamps, so a weighted block scores "
        "dated observations rather than a vector typed into the file. The data family "
        "follows 'variable': discharge from hydrometry, head from piezometry, stage "
        "from lake_levels. Mutually exclusive with 'observed_values'. The station is "
        "located by its own record and not by coordinates written beside it, so this "
        "output and the single-metric route read the same cell and their costs are "
        "comparable; a station the project cannot locate is refused by name rather "
        "than scored on another quantity.",
        json_schema_extra=field_metadata(site_scoped=True),
    )

    @model_validator(mode="after")
    def _check_one_source_of_observations(self):
        if self.observes is not None and self.observed_values is not None:
            raise ValueError(
                f"an output declares both observes={self.observes!r} and "
                "observed_values; they are two answers to one question. Keep 'observes' "
                "to score the loaded record, or 'observed_values' to score the vector "
                "written here."
            )
        reducer = getattr(self, "reducer", "none")
        if self.observes is not None and reducer != "none":
            raise ValueError(
                f"an output declares observes={self.observes!r} and reducer={reducer!r}; "
                "the record is paired with the simulated series step by step, so the "
                "reduced value is never scored. Drop 'reducer', or score a vector "
                "written in 'observed_values'."
            )
        return self


def _check_snap_radius(radius: Any, variable: str, *, support: str) -> None:
    """Refuse a snap radius that could not mean what it says."""
    if radius is None:
        return
    to = getattr(radius, "to", None)
    metres = float(radius.to("m").magnitude) if callable(to) else float(radius)
    if not metres > 0.0:
        raise ValueError(f"support={support!r}: snap_radius must be > 0 m, got {metres:g} m.")
    if str(variable) != "discharge":
        raise ValueError(
            f"support={support!r}: snap_radius moves a gauge onto the most accumulated "
            f"cell, and variable={variable!r} is not a discharge. A head or a lake state "
            "is read where it was measured, never on the talweg nearby."
        )


class CalibOutputPoint(ScoresAnObservedRecord, HydroModelBase):
    """Observable extracted at a planar ``(x, y)`` point.

    Use this variant for piezometric heads sampled at a single coordinate.
    Provide either ``x`` and ``y`` or a GeoJSON ``geometry`` block.
    """

    variable: Annotated[str, Profile.USER] = Field(
        description="Simulated variable to extract (e.g. 'head', 'outlet_discharge').",
        examples=["head"],
    )
    support: Annotated[Literal["point"], Profile.USER] = Field(
        default="point",
        description="Discriminator tag. 'point' reads the variable at (x, y).",
    )
    geometry: Annotated[dict[str, Any] | None, Profile.USER] = Field(
        default=None,
        description="GeoJSON point geometry. Coordinates are in meters.",
    )
    x: Annotated[Length | None, Profile.USER] = Field(
        default=None,
        description="X coordinate. Accepts a bare number (meters) or a pint string like "
        "'100 m'. Beside 'observes' it is not read, and loading warns so, unless "
        "snap_radius is set and the station's record carries no coordinate.",
    )
    y: Annotated[Length | None, Profile.USER] = Field(
        default=None,
        description="Y coordinate. Accepts a bare number (meters) or a pint string like "
        "'100 m'. Beside 'observes' it is not read, as for 'x'.",
    )
    time: Annotated[OutputTime, Profile.USER] = Field(
        default="all",
        description="'all' keeps every time step; 'last' / 'first' selects one.",
    )
    reducer: Annotated[OutputReducer, Profile.USER] = Field(
        default="none",
        description="How the values kept by time are reduced before they are scored "
        "against 'observed_values'. Refused beside 'observes': its record is paired "
        "with the series step by step.",
        json_schema_extra={"value_docs": OUTPUT_REDUCER_VALUE_DOCS},
    )
    observed_values: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        description="Hard-coded observed values, positional and dateless. Name a "
        "station in 'observes' to score a record the project loaded instead.",
    )
    snap_radius: Annotated[Length | None, Profile.USER] = Field(
        default=None,
        description="Opt-in. Move this gauge onto the cell that drains the most within "
        "this radius, before it is scored. Accepts a bare number (metres) or a pint "
        "string like '150 m'; it is a maximum displacement, measured from the gauge "
        "coordinate to the cell centres. The drained area is the one the solver routes "
        "on the mesh, along the descent D of the build. Only for 'variable' = "
        "'discharge'. With 'observes', a discharge station is then located by the "
        "coordinate of its record, which it otherwise is not, and snapped from there. "
        "Off by default: a gauge otherwise stays in the cell it resolves to, which may "
        "drain a small share of the catchment, and the run logs that share.",
    )

    @model_validator(mode="after")
    def _check_point_selectors(self) -> CalibOutputPoint:
        if self.observes is None and (self.x is None or self.y is None) and self.geometry is None:
            raise ValueError(
                "support='point' requires both 'x' and 'y', or 'geometry', unless "
                "'observes' names a station: its own record locates the point instead."
            )
        _check_snap_radius(self.snap_radius, self.variable, support="point")
        self._warn_about_a_position_nobody_reads()
        return self

    def _warn_about_a_position_nobody_reads(self) -> None:
        """Warn when x, y or geometry sit beside 'observes' and nothing reads them.

        A station named in 'observes' is located by its own record, so a
        position written beside it is ignored. Only a snap reads it, and only
        when the record carries no coordinate of its own. A warning and not a
        refusal: files written before this check still load.
        """
        if self.observes is None or self.snap_radius is not None:
            return
        written = [key for key in ("x", "y", "geometry") if getattr(self, key) is not None]
        if not written:
            return
        say(
            f"an output observes station {self.observes!r} and also writes "
            f"{', '.join(written)}. The station's own record locates it, so "
            f"{'they are' if len(written) > 1 else 'it is'} not read. Drop "
            f"{'them' if len(written) > 1 else 'it'}, or set snap_radius, the one "
            "option that falls back on a written position.",
            UserWarning,
            stacklevel=1,
        )


class CalibOutputBoundary(ScoresAnObservedRecord, HydroModelBase):
    """Observable extracted from a boundary package.

    Use this variant for fluxes integrated over a named boundary
    (drains, rivers, GHB) referenced by ``boundary_id``.
    """

    variable: Annotated[str, Profile.USER] = Field(
        description="Simulated variable to extract (e.g. 'discharge').",
    )
    support: Annotated[Literal["boundary"], Profile.USER] = Field(
        default="boundary",
        description="Discriminator tag. 'boundary' sums flux at boundary_id.",
    )
    boundary_id: Annotated[str, Profile.USER] = Field(
        description=(
            "Id of the boundary whose flux is summed, the key of its [flow.bc.<id>] table "
            "(for example 'drainage')."
        ),
        examples=["drainage"],
    )
    time: Annotated[OutputTime, Profile.USER] = Field(
        default="all",
        description="'all' keeps every time step; 'last' / 'first' selects one.",
    )
    reducer: Annotated[OutputReducer, Profile.USER] = Field(
        default="none",
        description="How the values kept by time are reduced before they are scored "
        "against 'observed_values'. Refused beside 'observes': its record is paired "
        "with the series step by step.",
        json_schema_extra={"value_docs": OUTPUT_REDUCER_VALUE_DOCS},
    )
    observed_values: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        description="Hard-coded observed values, positional and dateless. Name a "
        "station in 'observes' to score a record the project loaded instead.",
    )


class CalibOutputCell(ScoresAnObservedRecord, HydroModelBase):
    """Observable extracted at one structured cell.

    Use this variant for explicit ``(row, col)`` selectors on a structured
    grid. Without a ``layer`` the output reads the top active cell of the
    column, like any point given without a layer.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "cell_id": (
            "no solver reads a flat cell index. Name the cell with row and col "
            "(and layer), or place the output with support = 'point' and x, y."
        )
    }

    variable: Annotated[str, Profile.USER] = Field(
        description="Simulated variable to extract (e.g. 'head').",
    )
    support: Annotated[Literal["cell"], Profile.USER] = Field(
        default="cell",
        description="Discriminator tag. 'cell' reads one structured cell.",
    )
    row: Annotated[NonNegativeInt, Profile.USER] = Field(
        ...,
        description="Row of the cell on the structured grid, counted from 0 at the north edge.",
        examples=[10],
        json_schema_extra={"unit": "-"},
    )
    col: Annotated[NonNegativeInt, Profile.USER] = Field(
        ...,
        description="Column of the cell on the structured grid, counted from 0 at the west edge.",
        examples=[12],
        json_schema_extra={"unit": "-"},
    )
    layer: Annotated[NonNegativeInt | None, Profile.USER] = Field(
        default=None,
        description="Layer of the cell, counted from 0 at the top. Unset, the output "
        "reads the top active cell of the column, which is not layer 0 where that "
        "layer is pinched out or inactive.",
        json_schema_extra={"unit": "-"},
    )
    time: Annotated[OutputTime, Profile.USER] = Field(
        default="all",
        description="'all' keeps every time step; 'last' / 'first' selects one.",
    )
    reducer: Annotated[OutputReducer, Profile.USER] = Field(
        default="none",
        description="How the values kept by time are reduced before they are scored "
        "against 'observed_values'. Refused beside 'observes': its record is paired "
        "with the series step by step.",
        json_schema_extra={"value_docs": OUTPUT_REDUCER_VALUE_DOCS},
    )
    observed_values: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        description="Hard-coded observed values, positional and dateless. Name a "
        "station in 'observes' to score a record the project loaded instead.",
    )
    snap_radius: Annotated[Length | None, Profile.USER] = Field(
        default=None,
        description="Opt-in. Move this gauge onto the cell that drains the most within "
        "this radius, before it is scored. Accepts a bare number (metres) or a pint "
        "string like '150 m'; it is a maximum displacement, measured from the gauge "
        "cell centre to the cell centres. The drained area is the one the solver routes "
        "on the mesh, along the descent D of the build. Only for 'variable' = "
        "'discharge'. Off by default: a gauge otherwise stays in the cell it "
        "resolves to, which may drain a small share of the catchment, and the run logs "
        "that share.",
    )

    @model_validator(mode="after")
    def _check_cell_selectors(self) -> CalibOutputCell:
        _check_snap_radius(self.snap_radius, self.variable, support="cell")
        return self


class CalibOutputLake(ScoresAnObservedRecord, HydroModelBase):
    """Observable extracted from a MODFLOW 6 LAK lake state.

    Use this variant to score a lake water level, stored volume or free surface
    inside a composite objective. ``lake_id`` matches the lake declared under
    ``flow.sinks_sources.lakes.<lake_id>``.

    For calibration against a real observed chronicle, prefer the top-level
    ``variable = "lake_level"`` path: it loads the ``lake_levels`` data family
    and time-aligns the simulated stage to the observations. This output
    variant scores positionally against ``observed_values``, like the other
    composite outputs.
    """

    variable: Annotated[Literal["stage", "volume", "surface_area"], Profile.USER] = Field(
        default="stage",
        description=(
            "Simulated lake quantity: 'stage' (water level, m), 'volume' (m3) or "
            "'surface_area' (m2). All three are LAK observation states, read in native "
            "units and never time-scaled."
        ),
    )
    support: Annotated[Literal["lake"], Profile.USER] = Field(
        default="lake",
        description="Discriminator tag. 'lake' reads a LAK lake stage by lake_id.",
    )
    lake_id: Annotated[str, Profile.USER] = Field(
        description=(
            "Name of the lake to read, the <name> of its [flow.sinks_sources.lakes.<name>] table."
        ),
        examples=["lac0"],
    )
    time: Annotated[OutputTime, Profile.USER] = Field(
        default="all",
        description="'all' keeps every time step; 'last' / 'first' selects one.",
    )
    reducer: Annotated[OutputReducer, Profile.USER] = Field(
        default="none",
        description="How the values kept by time are reduced before they are scored "
        "against 'observed_values'. Refused beside 'observes': its record is paired "
        "with the series step by step.",
        json_schema_extra={"value_docs": OUTPUT_REDUCER_VALUE_DOCS},
    )
    observed_values: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        description="Hard-coded observed values, positional and dateless. Name a "
        "station in 'observes' to score a record the project loaded instead.",
    )


CalibOutputDecl: TypeAlias = Annotated[
    CalibOutputPoint | CalibOutputBoundary | CalibOutputCell | CalibOutputLake | CalibOutputNetwork,
    Field(
        discriminator="support",
        description="Discriminated union of calibration output variants selected by 'support'.",
    ),
]
"""Discriminated union of calibration output schemas keyed by ``support``."""


_CALIB_OUTPUT_ADAPTER: TypeAdapter[CalibOutputDecl] = TypeAdapter(CalibOutputDecl)


def validate_calib_output(
    payload: Any,
) -> (
    CalibOutputPoint | CalibOutputBoundary | CalibOutputCell | CalibOutputLake | CalibOutputNetwork
):
    """Validate one output mapping and return the concrete variant instance."""
    return _CALIB_OUTPUT_ADAPTER.validate_python(payload)


def outputs_agree(here: Any, there: Any) -> bool:
    """Say whether two output declarations describe the same output.

    Compared through the model rather than raw: a persisted document spells
    out every default (``time``, ``reducer``, ...) that a freshly written
    declaration leaves out, and the two describe the same output either way.

    Raises
    ------
    pydantic.ValidationError
        When either declaration does not validate as an output. A persisted
        output that still carries a removed key is refused for that key, not
        read as another output under the same name.
    """
    dumped_here = _CALIB_OUTPUT_ADAPTER.dump_python(
        _CALIB_OUTPUT_ADAPTER.validate_python(here), mode="json"
    )
    dumped_there = _CALIB_OUTPUT_ADAPTER.dump_python(
        _CALIB_OUTPUT_ADAPTER.validate_python(there), mode="json"
    )
    return dumped_here == dumped_there
