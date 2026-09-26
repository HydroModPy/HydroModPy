"""Pydantic model for the ``[calibration]`` TOML section.

Minimal TOML::

    [calibration]
    method       = "grid"
    max_iter     = 200
    save_runs    = "best_n"
    save_best_n  = 10
    seed         = 42

    [calibration.parameters]
    K  = { bounds = [1e-6, 1e-3] }
    Sy = { bounds = [0.02, 0.30] }

The name of the section is the name of the quantity: ``K`` is resolved against
what the project exposes, and ``hmp config targets`` prints the names a given
project carries.

Enriched TOML (twin-benchmark style)::

    [calibration]
    method = "cma_es"
    max_iter = 80
    seed = 42

    [calibration.parameters.K_aquifer]
    bounds = [1e-6, 1e-3]
    target = "flow.param.K.field.value"
    mode = "replace"

    [calibration.outputs.head_A]
    variable = "head"
    support = "point"
    x = 100.0
    y = 0.0
    observed_values = [42.1, 41.8, 41.5]

    [[calibration.objective_blocks]]
    name = "head_block"
    metric = "rmse"
    weight = 1.0
    uses_outputs = ["head_A"]
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field, TypeAdapter, ValidationError, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import NonEmptyStr, NonNegativeInt, PositiveFloat
from hydromodpy.core.stream_criterion_defaults import STREAM_CRITERION_DEFAULTS
from hydromodpy.core.units import Length

SaveRunsMode = Literal["none", "best_n", "all"]
ParameterMode = Literal["replace", "scale"]
OutputSupport = Literal["point", "boundary", "cell", "lake", "network"]
OutputReducer = Literal["mean", "sum", "last", "none"]
ObjectiveTransform = Literal["identity", "log", "inverse"]
PersistIterationDetail = Literal["none", "summary", "full"]
MetricKind = Literal[
    "rmse",
    "nse",
    "kge",
    "mae",
    "nse_log",
    "nse_delta",
    "nse_seasonal",
    "reservoir",
    "distance_gap",
    "distance_mean",
]
"""Metric names a TOML may select.

Kept equal to the keys of ``calibration.criteria.series.METRICS`` by
``tests/unit/calibration/test_metric_kind_matches_the_registry.py``: the engine
computed metrics this list did not offer, so they ran in Python and were refused
by validation.
"""
CalibrationMethod = NonEmptyStr
OutputTime = Literal["all", "last", "first"] | list[str]


class MatchingHydrographicNetworkOptions(HydroModelBase):
    """What a file may say about the protocol beyond naming it.

    Everything here has a default that reproduces the published method. The
    names are the ones the file uses for its own parameters and outputs, and the
    engines are free: the method is the pair of criteria and the order they run
    in, not the optimizer that walks them.
    """

    name: Annotated[Literal["matching_hydrographic_network"], Profile.USER] = Field(
        description="Protocol identifier.",
    )
    version: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Recipe version this file was written against. Unset runs the version this "
            "installation carries; pinned, a mismatch is refused rather than "
            "approximated, so a result that informed a decision stays replayable."
        ),
    )
    conductivity: Annotated[str, Profile.USER] = Field(
        default="K",
        description="Name of the calibration parameter stage one moves, as the file "
        "declares it under [calibration.parameters].",
    )
    storage: Annotated[str | None, Profile.USER] = Field(
        default="Sy",
        description="Name of the calibration parameter stage two moves. Null runs the "
        "network stage alone, which is a method in its own right: it identifies the "
        "conductivity without any discharge record.",
    )
    network_output: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Name of the network output stage one is scored on. Unset picks "
        "the single output declared with support='network'.",
    )
    steady_metric: Annotated[Literal["distance_gap", "distance_mean"], Profile.USER] = Field(
        default="distance_gap",
        description="Criterion of stage one. 'distance_gap' is the signed difference "
        "of Eq. 1, whose zero is the balance the paper solves for. 'distance_mean' is "
        "the mean offset: a diagnostic, and the estimator of the reference script, "
        "whose interior minimum sits nowhere in particular.",
    )
    steady_method: Annotated[str, Profile.USER] = Field(
        default="bisection",
        description="Engine of stage one. The signed criterion crosses zero once over "
        "several decades, which is what a root search wants; any registered engine is "
        "accepted.",
    )
    steady_max_iter: Annotated[int, Profile.USER] = Field(
        default=20,
        ge=1,
        description="Evaluation budget of stage one.",
    )
    steady_tolerance: Annotated[PositiveFloat | None, Profile.USER] = Field(
        default=None,
        description="How precisely stage one has to pin the conductivity before it "
        "stops, as a relative precision on the conductivity: 0.01 is the paper's one "
        "per cent. Unset takes the engine's default, which for the bisection is that "
        "same one per cent.",
    )
    steady_engine_options: Annotated[dict[str, Any], Profile.DEV] = Field(
        default_factory=dict,
        description="Options of the stage-one engine itself, named as that engine "
        "names them. Which ones exist depends on steady_method, and the model of "
        "each engine is in calibration.optim.method_config. A key the engine does not "
        "know is refused before the first solver call. The escape hatch for "
        "reproducing a published call; a "
        "precision is said once, in steady_tolerance.",
    )
    steady_window: Annotated[dict[str, str] | None, Profile.USER] = Field(
        default=None,
        description="Dates the steady stage averages, as {start, end}. Unset takes the "
        "whole [simulation.time] window.",
    )
    transient_metric: Annotated[str, Profile.USER] = Field(
        default="nse_log",
        description="Criterion of stage two. The default weights recessions as heavily "
        "as peaks, which is where storage shows.",
    )
    transient_method: Annotated[str, Profile.USER] = Field(
        default="scipy_nelder_mead",
        description="Engine of stage two.",
    )
    transient_max_iter: Annotated[int, Profile.USER] = Field(
        default=120,
        ge=1,
        description="Evaluation budget of stage two.",
    )
    transient_tolerance: Annotated[PositiveFloat | None, Profile.USER] = Field(
        default=None,
        description="How precisely stage two has to pin the storage before it stops, "
        "as a relative precision on the storage coefficient.",
    )
    transient_engine_options: Annotated[dict[str, Any], Profile.DEV] = Field(
        default_factory=dict,
        description="Options of the stage-two engine itself, named as that engine "
        "names them, and refused when it does not know them. Which ones exist depends "
        "on transient_method.",
    )
    discharge_variable: Annotated[str, Profile.USER] = Field(
        default="discharge",
        description="Observed variable stage two is scored on.",
    )
    observed_station_id: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Gauge whose cost drives stage two. Required when several stations are loaded.",
    )
    scoring_window: Annotated[dict[str, str] | None, Profile.USER] = Field(
        default=None,
        description="Dates bounding the samples stage two scores on, as {start, end}. "
        "Use it to drop the spin-up year the transient stage still has to simulate.",
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_the_bare_name(cls, data: Any) -> Any:
        """``protocol = "matching_hydrographic_network"`` is the whole declaration."""
        if isinstance(data, str):
            return {"name": data}
        return data


CalibrationProtocolDecl: TypeAlias = MatchingHydrographicNetworkOptions
"""What ``[calibration].protocol`` validates against.

One registered protocol today, so the alias names it directly. A second one
turns this into a union discriminated on ``name``; the registry and this alias
are kept in step by
``tests/unit/calibration/test_calibration_protocols.py``.
"""


class CalibParameterDecl(HydroModelBase):
    """User declaration for one calibrated parameter.

    The declaration is read from ``[calibration.parameters.<name>]``, and the
    section name is the quantity: it is resolved against the catalogue the
    project exposes, so a file states the range and nothing else. Writing
    ``path`` is the way out for whatever the catalogue does not reach, and it
    wins without a lookup.

    Use ``mode="replace"`` for direct parameter values and ``mode="scale"``
    for multiplicative factors applied to an existing config value.
    """

    bounds: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        min_length=2,
        max_length=2,
        description="[low, high] physical bounds, in the unit the target declares. "
        "Falls back to what the field annotates when the file omits it, which most "
        "fields deliberately leave unset because a range belongs to the site.",
    )
    transform: Annotated[Literal["identity", "log", "logit"], Profile.USER] = Field(
        default="identity",
        description="Transform applied before sampling. 'log' for "
        "strictly-positive quantities spanning orders of magnitude. Unset, the "
        "target's own field decides: a hydraulic conductivity declares 'log' where "
        "it is defined, so a file states this only to depart from it.",
    )
    prior: Annotated[Literal["uniform", "log_uniform", "normal"], Profile.USER] = Field(
        default="uniform",
        description="Prior distribution used by Bayesian samplers.",
    )
    path: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Dotted path into HydroModPyConfig. Optional, and the way out "
        "rather than the way in: when omitted, the section name is resolved against "
        "the project catalogue ('hmp config targets' lists it). Write one to reach a "
        "value the catalogue does not carry, or to settle a name two targets answer "
        "to. A path written here wins without a lookup, and a parameter that writes "
        "one inherits nothing from the field it points at.",
    )
    target: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Readable alias for 'path'. When both are set, 'target' wins.",
    )
    mode: Annotated[ParameterMode, Profile.USER] = Field(
        default="replace",
        description="'replace' writes the sampled value as-is; 'scale' multiplies "
        "the base TOML value at the target path by the sample.",
    )
    units: Annotated[str | None, Profile.USER] = Field(
        default=None, description="Parameter units label."
    )

    def resolve_target(self) -> str | None:
        """Return ``target`` when set, else ``path`` (read-only helper)."""
        return self.target if self.target is not None else self.path


class ScoresAnObservedRecord:
    """Shared observation surface for the outputs that carry a time axis.

    An output says what it is compared against in one of two ways, never both:
    ``observes`` names a station whose loaded record is aligned on the simulated
    timestamps, and ``observed_values`` is a positional vector written into the
    file. A network output inherits neither: its criterion balances two
    simulated quantities and has no record to fit.
    """

    observes: Annotated[str | None, Profile.USER] = Field(
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
    )
    support: Annotated[Literal["point"], Profile.USER] = Field(
        default="point",
        description="Discriminator tag. 'point' reads the variable at (x, y).",
    )
    geometry: Annotated[dict[str, Any] | None, Profile.USER] = Field(
        default=None,
        description="GeoJSON point geometry. Coordinates are in metres.",
    )
    x: Annotated[Length | None, Profile.USER] = Field(
        default=None,
        description="X coordinate. Accepts a bare number (metres) or a pint string like '100 m'.",
    )
    y: Annotated[Length | None, Profile.USER] = Field(
        default=None,
        description="Y coordinate. Accepts a bare number (metres) or a pint string like '100 m'.",
    )
    time: Annotated[OutputTime, Profile.USER] = Field(
        default="all",
        description="'all' keeps every time step; 'last' / 'first' selects one; "
        "a list of ISO timestamps selects specific steps.",
    )
    reducer: Annotated[OutputReducer, Profile.USER] = Field(
        default="none",
        description="Aggregation over the retained time slice.",
    )
    observed_values: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        description="Hard-coded observed values, positional and dateless. Name a "
        "station in 'observes' to score a record the project loaded instead.",
    )
    diagonal_neighbors: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Route this cell's discharge, and the area it drains, over shared "
        "nodes rather than shared edges, which recovers a talweg that runs diagonally "
        "across a square grid. Only reaches 'variable' = 'discharge'; a head or a lake "
        "state read at this point ignores it. The same knob as the network output's own "
        "'diagonal_neighbors', declared here too because a point output belongs to no "
        "network block.",
    )
    snap_radius: Annotated[Length | None, Profile.USER] = Field(
        default=None,
        description="Opt-in. Move this gauge onto the cell that drains the most within "
        "this radius, before it is scored. Accepts a bare number (metres) or a pint "
        "string like '150 m'; it is a maximum displacement, measured from the gauge "
        "coordinate to the cell centres. The drained area is the one the solver routes "
        "on the mesh, with this output's 'diagonal_neighbors'. Only for 'variable' = "
        "'discharge'. With 'observes', a discharge station is then located by the "
        "coordinate of its record, which it otherwise is not, and snapped from there. "
        "Off by default: a gauge otherwise stays in the cell it resolves to, which may "
        "drain a small share of the catchment, and the run logs that share.",
    )

    @model_validator(mode="after")
    def _check_point_selectors(self) -> CalibOutputPoint:
        if (self.x is None or self.y is None) and self.geometry is None:
            raise ValueError("support='point' requires both 'x' and 'y', or 'geometry'.")
        _check_snap_radius(self.snap_radius, self.variable, support="point")
        return self


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
        description="Boundary package identifier.",
    )
    time: Annotated[OutputTime, Profile.USER] = Field(
        default="all",
        description="'all' keeps every time step; 'last' / 'first' selects one; "
        "a list of ISO timestamps selects specific steps.",
    )
    reducer: Annotated[OutputReducer, Profile.USER] = Field(
        default="none",
        description="Aggregation over the retained time slice.",
    )
    observed_values: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        description="Hard-coded observed values, positional and dateless. Name a "
        "station in 'observes' to score a record the project loaded instead.",
    )


class CalibOutputCell(ScoresAnObservedRecord, HydroModelBase):
    """Observable extracted at one structured cell.

    Use this variant for explicit ``(row, col)`` selectors on a structured
    grid, optionally with a non-zero ``layer``. ``cell_id`` is a flat index
    accepted on backends that expose one.
    """

    variable: Annotated[str, Profile.USER] = Field(
        description="Simulated variable to extract (e.g. 'head').",
    )
    support: Annotated[Literal["cell"], Profile.USER] = Field(
        default="cell",
        description="Discriminator tag. 'cell' reads one structured cell.",
    )
    cell_id: Annotated[NonNegativeInt | None, Profile.USER] = Field(
        default=None,
        description="Flat cell index when the backend exposes one.",
    )
    row: Annotated[NonNegativeInt | None, Profile.USER] = Field(
        default=None,
        description="Structured row index.",
    )
    col: Annotated[NonNegativeInt | None, Profile.USER] = Field(
        default=None,
        description="Structured column index.",
    )
    layer: Annotated[NonNegativeInt, Profile.USER] = Field(
        default=0,
        description="Structured layer index.",
    )
    time: Annotated[OutputTime, Profile.USER] = Field(
        default="all",
        description="'all' keeps every time step; 'last' / 'first' selects one; "
        "a list of ISO timestamps selects specific steps.",
    )
    reducer: Annotated[OutputReducer, Profile.USER] = Field(
        default="none",
        description="Aggregation over the retained time slice.",
    )
    observed_values: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        description="Hard-coded observed values, positional and dateless. Name a "
        "station in 'observes' to score a record the project loaded instead.",
    )
    diagonal_neighbors: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Route this cell's discharge, and the area it drains, over shared "
        "nodes rather than shared edges, which recovers a talweg that runs diagonally "
        "across a square grid. Only reaches 'variable' = 'discharge'; a head read at this "
        "cell ignores it. The same knob as the network output's own 'diagonal_neighbors', "
        "declared here too because a cell output belongs to no network block.",
    )
    snap_radius: Annotated[Length | None, Profile.USER] = Field(
        default=None,
        description="Opt-in. Move this gauge onto the cell that drains the most within "
        "this radius, before it is scored. Accepts a bare number (metres) or a pint "
        "string like '150 m'; it is a maximum displacement, measured from the gauge "
        "cell centre to the cell centres. The drained area is the one the solver routes "
        "on the mesh, with this output's 'diagonal_neighbors'. Only for 'variable' = "
        "'discharge'. Off by default: a gauge otherwise stays in the cell it "
        "resolves to, which may drain a small share of the catchment, and the run logs "
        "that share.",
    )

    @model_validator(mode="after")
    def _check_cell_selectors(self) -> CalibOutputCell:
        if self.cell_id is None and (self.row is None or self.col is None):
            raise ValueError("support='cell' requires 'cell_id' or both 'row' and 'col'.")
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
        description="Lake identifier, matching flow.sinks_sources.lakes.<lake_id>.",
    )
    time: Annotated[OutputTime, Profile.USER] = Field(
        default="all",
        description="'all' keeps every time step; 'last' / 'first' selects one; "
        "a list of ISO timestamps selects specific steps.",
    )
    reducer: Annotated[OutputReducer, Profile.USER] = Field(
        default="none",
        description="Aggregation over the retained time slice.",
    )
    observed_values: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        description="Hard-coded observed values, positional and dateless. Name a "
        "station in 'observes' to score a record the project loaded instead.",
    )


class CalibOutputNetwork(HydroModelBase):
    """The mapped stream network as a calibration target.

    The model is compared to a hydrographic network rather than to a gauge:
    for every cell where it releases water to the surface, the descent to the
    mapped network is measured, and reciprocally. The output produces the pair
    ``(D_so, D_os)``; the metric on top of it is ``distance_gap``, their signed
    difference in absolute value, whose zero is the balance between an excess
    of simulated stream and a missing one.

    There is no ``observed_values`` here and there cannot be: the criterion
    balances two simulated quantities against each other, so nothing in it is
    fitted to a record. The mapped network enters as a geometry, not as a
    series, and exactly one of ``observed_network`` and
    ``stream_geometry_path`` names where it comes from.
    """

    variable: Annotated[str, Profile.USER] = Field(
        default="release_flux",
        description="Per-cell observable read from the solver, in m3/s, positive "
        "when the aquifer feeds the surface.",
    )
    support: Annotated[Literal["network"], Profile.USER] = Field(
        default="network",
        description="Discriminator: compare a simulated stream network to a mapped one.",
    )
    observed_network: Annotated[
        Literal["data.hydrography", "geographic.river_network"] | None, Profile.USER
    ] = Field(
        default=None,
        description="Where the mapped network comes from when it is not an explicit "
        "file. Exactly one of this and 'stream_geometry_path' must be set.",
        json_schema_extra={
            "value_docs": {
                "data.hydrography": "Reuses the network the hydrography data family "
                "already loaded (a local file or an osm / bdtopage / euhydro "
                "download), clipped to the delineated catchment. Costs nothing new "
                "to configure but ties the criterion to whatever that section "
                "resolved.",
                "geographic.river_network": "Derives the network from the DEM by a "
                "drainage-area threshold. K/R shapes both where the water table "
                "reaches the surface and the accumulation the threshold is cut on, so "
                "the criterion partly fits a seepage density onto a geomorphological "
                "one; warned once and recorded on every run that uses it.",
            }
        },
    )
    stream_geometry_path: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Vector file holding the mapped stream network, read only from "
        "here: the criterion resolves no geometry of its own and does not reuse the "
        "one the hydrography data family loaded. The way out of 'observed_network' "
        "when neither of its two sources is the one you want scored.",
    )

    @model_validator(mode="after")
    def _validate_observed_network_source(self) -> CalibOutputNetwork:
        """Exactly one of the two observation routes must be declared.

        Keyed on the values and not on ``model_fields_set``: both fields default
        to ``None``, so a value says everything a declaration would, and a
        configuration that has been through ``model_dump`` still validates. A
        dump writes every field, defaults included, and re-validating one marks
        them all as declared; keying on that would refuse a session record, a
        frozen run config and every test that round-trips an output.

        TOML carries no null, so "declared and null" is not a case a file can
        reach.
        """
        declared_network = self.observed_network is not None
        declared_path = self.stream_geometry_path is not None
        if declared_network and declared_path:
            raise ValueError(
                "calibration output declares both 'observed_network' "
                f"({self.observed_network!r}) and 'stream_geometry_path' "
                f"({self.stream_geometry_path!r}): the criterion would score one "
                "and the report would name the other. Declare exactly one."
            )
        if not declared_network and not declared_path:
            raise ValueError(
                "calibration output declares neither 'observed_network' nor "
                "'stream_geometry_path': the mapped network has no source. Pick "
                "one of 'data.hydrography', 'geographic.river_network', or set "
                "'stream_geometry_path' to an explicit file."
            )
        return self

    tau_specific_ratio: Annotated[float, Profile.USER] = Field(
        default=STREAM_CRITERION_DEFAULTS.tau_specific_ratio,
        ge=0.0,
        description="A cell releasing less than this fraction of its own recharge is "
        "not a seepage face. Zero reproduces the purely geometric criterion of the "
        "paper. Frozen over the whole search: a threshold moving with the trial would "
        "cost the criterion its monotonicity.",
    )
    weighting: Annotated[Literal["cell", "area"], Profile.USER] = Field(
        default="cell",
        description="Average one cell one vote (the paper) or weighted by cell area. "
        "Both values are always reported; use 'area' on a mesh refined along the "
        "streams, where cell density is highest exactly where distances are smallest.",
    )
    diagonal_neighbors: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Route over shared nodes rather than shared edges, which recovers "
        "the diagonal descents of a D8 grid. Only meaningful on a structured quad mesh. "
        "The default is the literal reading of the paper and it is not a second-decimal "
        "choice: on a synthetic valley whose talweg runs along the grid diagonal, the "
        "most accumulated cell collects 6.6 per cent of the domain over shared edges and "
        "100 per cent over shared nodes, and the delineation that produced the catchment "
        "itself uses a D8 pointer. Set it to true wherever the talwegs are not "
        "axis-aligned, which on real topography is most of them.",
    )
    observed_position_accuracy: Annotated[Length | None, Profile.USER] = Field(
        default=None,
        description="Positional accuracy of the mapped network. The validity ratio is "
        "normalised by max(cell size, this), because the error floor is set by the "
        "network's own precision and not by the model resolution. Unset is the "
        "literal reading of the paper.",
    )
    roptim_max: Annotated[PositiveFloat, Profile.USER] = Field(
        default=2.0,
        description="Validity bound of Eq. 4. It qualifies the result and never "
        "penalises the cost: a bad ratio says the agreement is coarse, not that the "
        "calibrated value should be discarded.",
    )
    on_roptim_violation: Annotated[Literal["warn", "error"], Profile.USER] = Field(
        default="warn",
        description="What a violation of the validity bound does. Default warns and "
        "returns the value, because a calibration is asked for a number.",
    )
    max_unreachable_fraction: Annotated[float, Profile.USER] = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Bound on 'frac_unreachable_so' alone: the share of the simulated "
        "network whose descent never meets the mapped one, whose target does not move "
        "between trials. Beyond a few per cent the routing surface is not conditioned "
        "and D_so would be a fiction. The reciprocal share, 'frac_unreachable_os', is "
        "reported and deliberately left unbounded: its target is the simulated network, "
        "which the search itself retracts.",
    )
    alpha_warning_threshold: Annotated[float, Profile.EXPERT] = Field(
        default=STREAM_CRITERION_DEFAULTS.alpha_warning_threshold,
        gt=0.0,
        le=1.0,
        description="Below this value of 'alpha_obs_closure_catchment' the run warns "
        "that its distances carry a top-versus-map disagreement on top of the "
        "hydrogeology. alpha is the share of the downstream closure of the mapped "
        "network the network itself covers, measured on the MODEL TOP and on the "
        "catchment. It changes nothing that is computed: the criterion is scored the "
        "same way above and below it.",
    )
    clipping_warning_share: Annotated[float, Profile.EXPERT] = Field(
        default=STREAM_CRITERION_DEFAULTS.clipping_warning_share,
        ge=0.0,
        le=1.0,
        description="Share of the mapped stream cells lying outside the delineated "
        "catchment above which the whole-mesh alpha is reported as unreadable. Those "
        "reaches trace through the buffer, where no cell is required to descend into "
        "the network, so they inflate the closure without adding to the numerator. "
        "Reported together with clipping_warning_gap, never alone.",
    )
    clipping_warning_gap: Annotated[float, Profile.EXPERT] = Field(
        default=STREAM_CRITERION_DEFAULTS.clipping_warning_gap,
        ge=0.0,
        le=1.0,
        description="Minimum absolute gap between the whole-mesh and the catchment "
        "alpha for the clipping report to fire. A linework spilling out of the "
        "catchment over ground that routes the same way leaves the two ratios equal, "
        "and reporting it there would be noise on every ordinary project.",
    )
    time: Annotated[OutputTime, Profile.USER] = Field(
        default="last",
        description="Which timesteps the release flux is read at. Phase one runs a "
        "single steady period, so 'last' is the whole run.",
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


class CalibScoringWindow(HydroModelBase):
    """Dates bounding the samples a metric is computed on.

    A window in dates rather than in sample counts: it says the same thing
    whatever the output frequency, whereas ``warmup_periods`` counts samples
    after alignment and therefore means a different span at daily and at weekly
    resolution. The two are mutually exclusive, which
    :class:`CalibrationConfig` enforces.
    """

    start: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="First date scored, ISO 8601. Unset means from the first sample.",
    )
    end: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Last date scored, ISO 8601. Unset means up to the last sample.",
    )

    @model_validator(mode="after")
    def _check_bounds(self) -> CalibScoringWindow:
        bounds = _parsed_scoring_bounds(self)
        if bounds[0] is not None and bounds[1] is not None and bounds[0] > bounds[1]:
            raise ValueError(f"scoring_window start {self.start!r} is after end {self.end!r}.")
        return self


def _parsed_scoring_bounds(window: CalibScoringWindow) -> tuple[Any, Any]:
    """Parse the window bounds into timestamps, raising on a bad date."""
    import pandas as pd

    parsed = []
    for label, raw in (("start", window.start), ("end", window.end)):
        if raw is None:
            parsed.append(None)
            continue
        try:
            parsed.append(pd.Timestamp(raw))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"scoring_window {label}={raw!r} is not a date.") from exc
    return parsed[0], parsed[1]


def scoring_window_bounds(window: CalibScoringWindow | None) -> tuple[Any, Any] | None:
    """Return the parsed ``(start, end)`` of a window, or None when unset."""
    if window is None:
        return None
    return _parsed_scoring_bounds(window)


class CalibObjectiveBlockDecl(HydroModelBase):
    """Weighted metric block used by a composite objective.

    A block consumes one or more named outputs, applies one metric, and
    contributes ``weight`` to the final minimization cost. Blocks make mixed
    objectives explicit, for example combining heads, discharge, and transport
    signals in one calibration session.
    """

    name: Annotated[str, Profile.USER] = Field(
        description="Unique block identifier used in logs and persistence.",
    )
    metric: Annotated[MetricKind, Profile.USER] = Field(
        default="rmse",
        description="Metric key. One of rmse, nse, kge, mae, nse_log.",
        json_schema_extra={
            "value_docs": {
                "rmse": "Root-mean-square error, in the observed unit; penalizes large "
                "misfits most.",
                "nse": "Nash-Sutcliffe efficiency against the observed mean; the "
                "standard choice for a level or discharge series.",
                "kge": "Kling-Gupta efficiency; separates correlation, variability "
                "and bias when NSE alone is ambiguous.",
                "mae": "Mean absolute error, in the observed unit; less sensitive to "
                "outliers than RMSE.",
                "nse_log": "NSE on log-transformed series; weights low flows as "
                "heavily as peaks, good for recessions.",
                "nse_delta": "NSE on the increments of the series rather than its "
                "level; a level is an integral and can hide flux errors that "
                "compensate, which only its increments show.",
                "nse_seasonal": "NSE against the seasonal cycle rather than the "
                "overall mean; asks whether the model beats climatology.",
                "reservoir": "Half nse_seasonal plus half nse_delta, built for an "
                "impounded level: a plain NSE there is beaten by the seasonal cycle, "
                "and the increments are what carry the flux errors.",
                "distance_gap": "Balances the simulated stream network against the "
                "mapped one; zero marks the crossing.",
                "distance_mean": "Mean spatial offset between simulated and mapped "
                "streams; a diagnostic, not a substitute for distance_gap.",
            }
        },
    )
    weight: Annotated[PositiveFloat, Profile.USER] = Field(
        default=1.0,
        description="Relative weight of this block in the composite sum.",
    )
    uses_outputs: Annotated[list[str], Profile.USER] = Field(
        min_length=1,
        description="Outputs (by name) consumed by this block.",
    )
    normalize_cost: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="When True, divide the block cost by a reference scale "
        "(observed std fallback mean absolute value).",
    )
    transform: Annotated[ObjectiveTransform, Profile.USER] = Field(
        default="identity",
        description="Per-block cost transform applied before weighting. Note that "
        "transform='log' takes the logarithm of the cost, which is not the same "
        "thing as metric='nse_log', an NSE computed on log-transformed series.",
        json_schema_extra={
            "value_docs": {
                "identity": "Uses the block cost as computed, with no transform.",
                "log": "Takes log10 of the cost plus a small epsilon, compressing "
                "large costs before weighting.",
                "inverse": "Takes -1 / (cost + epsilon), sharpening the gradient near "
                "a cost of zero.",
            }
        },
    )
    warmup: Annotated[NonNegativeInt | None, Profile.USER] = Field(
        default=None,
        description=(
            "Burn-in periods dropped from this block only, overriding "
            "[calibration].warmup_periods. Leave unset to inherit it; set it to 0 to "
            "switch the burn-in off for this block."
        ),
    )

    @model_validator(mode="after")
    def _check_the_normalisation_means_something(self) -> CalibObjectiveBlockDecl:
        """Refuse here what the objective would refuse at the first trial.

        The reader of this message writes TOML, so the refusal belongs where the
        file is read rather than hours later inside a search.
        """
        if self.normalize_cost:
            from hydromodpy.calibration.optim.objective import (
                refuse_a_normalisation_that_means_nothing,
            )

            refuse_a_normalisation_that_means_nothing(self.name, str(self.metric).lower())
        return self


PHASE_REGIME_PATHS: dict[str, tuple[str, ...]] = {
    "steady": (
        "flow.flow_regime",
        "simulation.time.start_datetime",
        "simulation.time.end_datetime",
        "simulation.time.step_unit",
        "simulation.time.step_value",
    ),
    "transient": ("flow.flow_regime",),
}
"""The dotted paths a phase's ``regime`` writes, by regime.

``runners/phase_regime.py`` writes them. They are listed here because a phase
that also writes one of them in ``overrides`` is refused when the file is read,
and ``config`` does not import ``runners``.
``tests/unit/calibration/test_phase_regime.py`` keeps the two equal.
"""


def fold_a_legacy_regime(
    phase: Mapping[str, Any], steady_window: Mapping[str, Any] | None = None
) -> dict[str, Any] | None:
    """Return a phase written with its regime as overrides, rewritten with ``regime``.

    Runs sealed before ``regime`` existed carry each protocol stage in that
    spelling, and reading one back must not refuse it as a contradiction of the
    protocol that wrote it.

    The spelling is a phase with no ``regime`` whose ``overrides`` hold every
    path ``PHASE_REGIME_PATHS`` lists for its ``flow.flow_regime``. Those paths
    are dropped and every other override is kept. When the protocol names a
    ``steady_window``, the sealed bounds have to be the same instants; otherwise
    they are trusted, since the file was written from its own
    ``[simulation.time]``. Returns None for any other phase, and for a window
    that does not match.
    """
    if phase.get("regime") is not None:
        return None
    overrides = phase.get("overrides")
    if not isinstance(overrides, Mapping):
        return None
    regime = overrides.get("flow.flow_regime")
    paths = PHASE_REGIME_PATHS.get(regime) if isinstance(regime, str) else None
    if paths is None or not all(path in overrides for path in paths):
        return None
    folded = dict(phase)
    folded["regime"] = regime
    folded["overrides"] = {key: value for key, value in overrides.items() if key not in paths}
    if steady_window is not None and regime == "steady":
        sealed = (
            overrides["simulation.time.start_datetime"],
            overrides["simulation.time.end_datetime"],
        )
        named = (steady_window.get("start"), steady_window.get("end"))
        if not all(_same_instant(a, b) for a, b in zip(sealed, named, strict=True)):
            return None
        folded["steady_window"] = dict(steady_window)
    return folded


def _same_instant(a: Any, b: Any) -> bool:
    """Say whether two spellings name the same instant."""
    import pandas as pd

    try:
        return bool(pd.Timestamp(a) == pd.Timestamp(b))
    except (TypeError, ValueError):
        return False


_OPTIONS_WITHOUT_AN_ENGINE = (
    "{where} gives optimizer_kwargs and no method. They are options of one engine, "
    "and a search that names no method gets the one its criteria call for. Write "
    "method beside them, or drop them."
)


UncertaintyMethod = Literal["cost_profile", "multistart", "linearized"]


def _refuse_a_posterior(data: Any, where: str) -> None:
    """Answer 'posterior' with the reason it is not offered, instead of an enum error."""
    if isinstance(data, Mapping) and str(data.get("method", "")).strip() == "posterior":
        raise ValueError(
            f"{where} method='posterior' is not offered, and the "
            "reason is worth stating rather than hiding behind a list. A posterior "
            "is a statement about probability, so it needs a likelihood, and a "
            "likelihood needs a criterion built from residuals with an error model "
            "on each observation. An efficiency score is not one: NSE, KGE and "
            "nse_log are aggregates already stripped of their units, and a "
            "posterior computed from one would carry a precision nothing "
            "established. Sampling it also costs thousands of model runs, not the "
            "one per parameter that 'linearized' costs. Use 'linearized', which "
            "reports a first-order width and the parameter tradeoffs from "
            "residuals, or 'multistart', which reports the spread of restarted "
            "searches, and say in the write-up which of the two the number rests "
            "on."
        )


class CalibPhaseUncertaintyDecl(HydroModelBase):
    """How wide one phase says its answer is, key by key over ``[calibration.uncertainty]``.

    Every key is optional and has the meaning it has in the section. A key
    written here wins for this phase. A key left out takes the section's value,
    then the default that follows what the phase scores. ``restarts`` and
    ``perturbation`` belong to a method: a phase that names another method than
    the section does not inherit them.
    """

    method: Annotated[UncertaintyMethod | None, Profile.USER] = Field(
        default=None,
        description="How this phase's interval is obtained: 'cost_profile', "
        "'multistart' or 'linearized', read as in [calibration.uncertainty] method.",
    )
    restarts: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=2,
        description="How many times method='multistart' repeats this phase's search.",
    )
    perturbation: Annotated[PositiveFloat | None, Profile.USER] = Field(
        default=None,
        description="Relative step of method='linearized' for this phase, as a fraction "
        "of each calibrated value.",
    )
    tolerance: Annotated[PositiveFloat | None, Profile.USER] = Field(
        default=None,
        description="Width of this phase's interval: a fraction of the best cost when "
        "mode='relative', a number in the unit of the cost (metres for a network "
        "distance) when mode='absolute'. Unset here and in [calibration.uncertainty], "
        "one mesh cell for a phase scored only by network distances, five per cent of "
        "the best cost otherwise.",
    )
    mode: Annotated[Literal["relative", "absolute"] | None, Profile.USER] = Field(
        default=None,
        description="How this phase's tolerance is read. Unset here and in "
        "[calibration.uncertainty], 'absolute' for a phase scored only by network "
        "distances, 'relative' otherwise.",
    )

    @model_validator(mode="before")
    @classmethod
    def _say_why_a_posterior_is_not_one_of_these(cls, data: Any) -> Any:
        """Answer 'posterior' the way the section does."""
        _refuse_a_posterior(data, "a phase's uncertainty")
        return data


class CalibPhaseDecl(HydroModelBase):
    """One stage of a calibration that runs in several.

    A phase selects, by name, from the parameters, outputs and objective blocks
    the calibration already declares: nothing is redeclared, so the two stages
    of a method cannot drift apart in a single file. What a phase carries of
    its own is its search: a method, a budget, and which parameters it is
    allowed to move.

    ``freeze_on_success`` means this phase passes the values it found to the
    phases after it. A later phase holds them fixed, unless it lists the
    parameter: it then moves it again, starting from the passed value when its
    method accepts a start point. It reads "pass on if the phase converged",
    never "pass on if the result is good": a validity indicator qualifies a
    result, and a phase that returns a coarse agreement still returns a number.
    The state of that indicator travels to the later phases and into the
    report, so a value calibrated on top of a doubtful one carries the mention
    all the way out.
    """

    name: Annotated[NonEmptyStr, Profile.USER] = Field(
        description="Phase identifier, unique in the calibration and used in the "
        "session directory and in the report.",
    )
    description: Annotated[str, Profile.USER] = Field(
        default="",
        description="What this phase calibrates and against what, in one sentence.",
    )
    method: Annotated[CalibrationMethod | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optimization method for this phase only. Unset, it follows from what the "
            "phase scores: 'bisection' when the phase moves one parameter in log space "
            "and every one of its blocks is signed (distance_gap), since the answer is "
            "then a zero to find; 'scipy_nelder_mead' otherwise, a cost to minimise. "
            "hmp calibrate --list-phases prints the method and why. Write it to "
            "depart from that choice, and whenever optimizer_kwargs are given. "
            "Built-ins: 'grid' (regular sweep, sized by "
            "optimizer_kwargs.points_per_dim), 'random_search', 'bisection' (root of "
            "a signed criterion on one parameter, the stream-network stage), 'optuna' "
            "(TPE), 'cma_es', 'scipy_de', 'scipy_nelder_mead', 'gp_mapping', "
            "'da_mh_gp'. An unknown name is refused when the optimizer is built, "
            "with the list installed here."
        ),
    )
    max_iter: Annotated[int, Profile.USER] = Field(
        default=100,
        ge=1,
        description="Maximum number of evaluations for this phase.",
    )
    tolerance: Annotated[PositiveFloat | None, Profile.USER] = Field(
        default=None,
        description=(
            "How precisely the search has to pin a parameter before it stops, as a "
            "relative precision on the parameter itself: 0.01 asks for one per cent, "
            "0.1 for ten. On a log-transformed parameter that is a ratio, which is "
            "how a conductivity is known in the first place, and it holds wherever the "
            "value sits; on any other transform there is no scale on the value to be "
            "relative to before the search has one, so it reads as a fraction of the "
            "declared interval. Each engine's own stopping option is written from it, "
            "so the same number survives a change of engine, and the engine's own "
            "option stays available for reproducing a published call verbatim. Unset, "
            "the engine's default applies. An engine that stops on its budget rather "
            "than on a precision refuses this rather than ignore it."
        ),
    )
    batch_size: Annotated[int, Profile.DEV] = Field(
        default=1,
        ge=1,
        description="Suggestions drawn per ask. A root search returns one point at a "
        "time during its refinement, whatever this asks for.",
    )
    parallel: Annotated[int, Profile.DEV] = Field(
        default=1,
        ge=1,
        description="Trials evaluated concurrently inside one batch.",
    )
    parameters: Annotated[list[str], Profile.USER] = Field(
        min_length=1,
        description="Names of the calibration parameters this phase may move. Every "
        "other parameter keeps the value it entered the phase with.",
    )
    outputs: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Names of the calibration outputs this phase scores on. Empty "
        "means every declared output.",
    )
    objective_blocks: Annotated[list[str] | dict[str, PositiveFloat], Profile.USER] = Field(
        default_factory=list,
        description="Objective blocks this phase evaluates. Empty means every declared "
        "block. A list names them and keeps their declared weight. A table gives each "
        "named block the phase's own share instead, {block = share}, normalised to sum "
        "to one like a block's weight already is; every key must be a declared block, "
        "and every share must be positive.",
    )
    variable: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Single-metric variable, when this phase does not use blocks.",
    )
    objective: Annotated[MetricKind | None, Profile.USER] = Field(
        default=None,
        description="Metric scoring this phase's single simulated series, when the "
        "phase does not use objective blocks. Same vocabulary as a block's 'metric'.",
    )
    observed_station_id: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Observed station whose cost the optimizer minimises. Every loaded gauge is already scored at its own mesh cell, on the discharge routed to that cell, and every cost is reported; naming one says which of them drives the search. Required when several stations are loaded, optional with one. Overrides the calibration-level value for this phase.",
    )
    optimizer_kwargs: Annotated[dict[str, Any], Profile.DEV] = Field(
        default_factory=dict,
        description="Extra keyword arguments forwarded to this phase's optimizer. They "
        "belong to one engine, so a phase that gives them names its method.",
    )
    regime: Annotated[Literal["steady", "transient"] | None, Profile.USER] = Field(
        default=None,
        description="Flow regime this phase runs, a property of the model and not of "
        "the search. 'steady' is one period over steady_window, by default the extent "
        "of [simulation.time]. 'transient' is the project's own time grid. Unset, the "
        "phase runs the model as the project and its overrides declare it.",
        json_schema_extra={
            "value_docs": {
                "steady": "One period over steady_window, so the recharge over it "
                "averages to its mean. A steady solve carries no storage.",
                "transient": "The project's time grid, with only the regime restated.",
            }
        },
    )
    steady_window: Annotated[dict[str, str] | None, Profile.USER] = Field(
        default=None,
        description="Dates the steady period spans, as {start, end}, when regime = "
        "'steady'. Unset takes the whole [simulation.time] window.",
    )
    overrides: Annotated[dict[str, Any], Profile.USER] = Field(
        default_factory=dict,
        description="Configuration values this phase runs with, as dotted paths into "
        "the project configuration. A phase that gives regime may not write here a "
        "path regime writes: that would say the same thing twice.",
    )
    scoring_window: Annotated[CalibScoringWindow | None, Profile.USER] = Field(
        default=None,
        description="Dates bounding the samples this phase scores on.",
    )
    depends_on: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Name of the phase that must run first. The values it passes on "
        "enter this one fixed, except those this phase lists and moves again.",
    )
    freeze_on_success: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Pass the values this phase found to the phases after it. A later "
        "phase holds them fixed, unless it lists the parameter: it then moves it again, "
        "starting from the passed value when its method accepts a start point. When two "
        "phases pass on the same parameter, the later one wins. Success means the phase "
        "converged, not that its validity indicator is good.",
    )
    uncertainty: Annotated[CalibPhaseUncertaintyDecl | None, Profile.USER] = Field(
        default=None,
        description="How wide this phase says its answer is, with the keys of "
        "[calibration.uncertainty]. A key written here wins for this phase; a key left "
        "out takes the section's value, then the default that follows what the phase "
        "scores: one mesh cell for a phase scored only by network distances, five per "
        "cent of the best cost otherwise. hmp calibrate --list-phases prints the width "
        "each phase reads and where it comes from.",
    )

    @property
    def is_single_metric(self) -> bool:
        """Whether this phase scores one variable rather than objective blocks.

        Declaring ``variable`` or ``objective`` picks the single-metric route.
        The phase then ignores the outputs and the blocks the calibration
        declares for the other phases, which would otherwise take precedence
        and score it on a criterion it never asked for.
        """
        return self.variable is not None or self.objective is not None

    @model_validator(mode="after")
    def _name_the_engine_the_options_belong_to(self) -> CalibPhaseDecl:
        """Refuse optimizer_kwargs on a phase that names no method.

        The options belong to one engine, and a phase that names none gets the
        one its criteria call for. The options would then reach an engine the
        file never chose.
        """
        if self.optimizer_kwargs and self.method is None:
            raise ValueError(_OPTIONS_WITHOUT_AN_ENGINE.format(where=f"phase {self.name!r}"))
        return self

    @model_validator(mode="after")
    def _say_the_regime_once(self) -> CalibPhaseDecl:
        """Refuse a regime said twice, and a steady window with no steady regime.

        ``regime`` writes its paths into the configuration the trials run with,
        and ``overrides`` writes into the same one. A path in both would leave
        the reader to guess which value the model ran with.
        """
        if self.steady_window is not None and self.regime != "steady":
            raise ValueError(
                f"phase {self.name!r} gives a steady_window and regime = {self.regime!r}. "
                'The window is the span of the one steady period: write regime = "steady", '
                "or drop the window."
            )
        if self.regime is None:
            return self
        twice = [path for path in PHASE_REGIME_PATHS[self.regime] if path in self.overrides]
        if twice:
            raise ValueError(
                f"phase {self.name!r} gives regime = {self.regime!r}, which writes "
                f"{', '.join(twice)}, and writes the same in overrides: two ways to say "
                "the same thing. Keep regime and drop these overrides, or drop regime."
            )
        return self


class CalibAggregateDecl(HydroModelBase):
    """How several scored targets become one cost.

    Two questions the word "weight" runs together. Whether an error is large for
    what the instrument can resolve is a property of the measurement, not a
    decision. What matters more between the outlet and the reservoir is a
    decision, and the modeller's. The cost is the product of both, never one of
    them, and this section names which recipe made them addable.

    The literature offers two named recipes and states they are incompatible: one
    over sigma, which makes each residual dimensionless and statistically
    defensible, and an equal share of the initial objective, which guarantees no
    data type is invisible to the search. There is no third to invent, only a
    choice to name and to record.
    """

    weighting: Annotated[Literal["manual", "error"], Profile.USER] = Field(
        default="manual",
        description=(
            "How the members are made comparable before the weights apply. "
            "'manual' takes the declared 'weight' of each block as the whole story, "
            "which is honest as long as the costs are already commensurable. "
            "'error' divides each residual by what its instrument resolves, so the "
            "members become pure numbers first; it needs a residual criterion and an "
            "observation carrying an error model, and is refused without both."
        ),
    )
    nested_gauges: Annotated[Literal["total", "incremental"], Profile.USER] = Field(
        default="total",
        description=(
            "How two gauges on imbricated catchments are read. 'total' scores each "
            "against its own full drained area, which is what a gauge measures; the "
            "residuals are then statistically dependent, and no standard correction "
            "exists for that. 'incremental' scores the downstream one on what its own "
            "reach adds, downstream minus upstream, which is the only mechanisable way "
            "to make the two independent. Neither is inferred: the overlap is measured "
            "and reported whichever is chosen."
        ),
    )
    min_samples: Annotated[int, Profile.USER] = Field(
        default=1,
        ge=1,
        description=(
            "Fewest paired samples a member may be scored on. An alignment that "
            "collapses to three days still returns a number, and a weight of 65 per "
            "cent resting on three days is not what the file says it is."
        ),
    )
    on_member_failure: Annotated[Literal["veto", "drop"], Profile.USER] = Field(
        default="veto",
        description=(
            "What one unscorable member does to the total. 'veto' makes the whole "
            "trial fail, which is the default because a partial cost is not "
            "comparable to a full one. 'drop' scores the survivors and records which "
            "member was left out, which has to be asked for explicitly."
        ),
    )


class CalibUncertaintyDecl(HydroModelBase):
    """How wide the search says its own answer is.

    The calibrated value never moves: this block only decides what is reported
    beside it. ``cost_profile`` reads the interval off the trials the search
    already ran, so it costs no extra model run and rests on no error model. It
    says what the search could not tell apart, which is a statement about the
    trace and not a posterior.
    """

    method: Annotated[UncertaintyMethod, Profile.USER] = Field(
        default="cost_profile",
        description=(
            "How the interval around each calibrated value is obtained. "
            "'cost_profile' reads the range of sampled values whose cost stayed within "
            "'tolerance' of the best, off the trace the search already produced, and "
            "costs no extra model run. 'multistart' runs the whole search 'restarts' "
            "times from 'restarts' different starting points and reports the spread of "
            "the optima it reaches, which is the only one of the two that can see a "
            "second basin; it costs that many times the runs. The calibrated value "
            "never moves either way: with 'multistart' it is the best of the restarts."
        ),
    )
    restarts: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=2,
        description=(
            "How many times the search is repeated by method='multistart'. Required by "
            "it and refused by any other method, because a number of restarts that "
            "nothing restarts is a statement about a run that did not happen. Each one "
            "is a full search: eight restarts of a hundred-evaluation phase is eight "
            "hundred model runs."
        ),
    )
    perturbation: Annotated[PositiveFloat | None, Profile.USER] = Field(
        default=None,
        description=(
            "Relative step the derivatives of method='linearized' are taken with, as a "
            "fraction of each calibrated value: 0.01 moves it by one per cent. Required by "
            "it and refused by any other method. Too small and the difference is solver "
            "noise; too large and it is no longer a derivative. One per cent is the usual "
            "starting point, and the honest check is to move it and see whether the "
            "reported width moves with it. 'linearized' costs one model run per parameter, "
            "reads derivatives around the answer instead of searching again, and is the "
            "only declared method that also reports which parameters trade off against "
            "which. It is first-order: exact where the model is linear about the optimum, "
            "approximate in proportion to the curvature, and not a posterior."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _say_why_a_posterior_is_not_one_of_these(cls, data: Any) -> Any:
        """Answer the word an operator will reasonably type, instead of an enum error.

        'posterior' is the obvious name for anyone who has read PEST or pyEMU, and
        the reason it is not offered is a position rather than an omission. Leaving
        them a bare list of three literals sends them looking for a bug.
        """
        _refuse_a_posterior(data, "[calibration.uncertainty]")
        return data

    @model_validator(mode="after")
    def _check_the_restarts_have_something_to_restart(self) -> CalibUncertaintyDecl:
        if self.method == "multistart" and self.restarts is None:
            raise ValueError(
                "[calibration.uncertainty] method='multistart' needs 'restarts': it says "
                "how many times the whole search is repeated, and each one costs a full "
                "search."
            )
        if self.method == "linearized" and self.perturbation is None:
            raise ValueError(
                "[calibration.uncertainty] method='linearized' needs 'perturbation': it "
                "is the relative step its derivatives are taken with, and there is no "
                "universal value because it trades solver noise against curvature."
            )
        if self.method != "linearized" and self.perturbation is not None:
            raise ValueError(
                f"[calibration.uncertainty] perturbation={self.perturbation!r} is only "
                f"read by method='linearized'; got method={self.method!r}, which takes no "
                "derivatives."
            )
        if self.method != "multistart" and self.restarts is not None:
            raise ValueError(
                f"[calibration.uncertainty] restarts={self.restarts!r} is only read by "
                f"method='multistart'; got method={self.method!r}, which reads the trace "
                "the single search already produced."
            )
        return self

    tolerance: Annotated[PositiveFloat | None, Profile.USER] = Field(
        default=None,
        description=(
            "Width of the interval. A fraction of the best cost when mode='relative' "
            "(0.05 = five per cent), and a number in the unit of the cost when "
            "mode='absolute'. Unset, it follows what the search scores: one mesh cell, "
            "in metres, for a search scored only by network distances (distance_gap, "
            "distance_mean), because a stream cannot move by less than a cell; 0.05 "
            "otherwise, five per cent of the best cost. The cell is the median distance "
            "between the centres of neighbouring cells, measured by the network "
            "criterion on the mesh it scores. A phase may write its own, which wins."
        ),
    )
    mode: Annotated[Literal["relative", "absolute"] | None, Profile.USER] = Field(
        default=None,
        description=(
            "How 'tolerance' is read. 'relative' is a fraction of the best cost and is "
            "the usual choice for an efficiency score. A criterion solved at zero, such "
            "as the stream-network gap, has no fraction of itself to take: state the "
            "width in the unit of the cost with 'absolute', for example 25 metres. "
            "Unset, 'absolute' for a search scored only by network distances and "
            "'relative' otherwise. hmp calibrate --check refuses 'relative' on a search "
            "scored only by network distances."
        ),
    )


class CalibrationConfig(HydroModelBase):
    """Top-level ``[calibration]`` section.

    The config selects the optimizer, iteration budget, candidate persistence
    policy, parameter declarations, observable outputs, and objective blocks.
    It is the stable user-facing schema used by CLI calibration and
    ``Project.calibrate``.

    When no explicit objective block is declared, HydroModPy can synthesize one
    from ``objective`` and ``variable`` if the matching output exists.
    """

    protocol: Annotated[CalibrationProtocolDecl | None, Profile.USER] = Field(
        default=None,
        description=(
            "Published calibration method this file runs, named instead of retyped. "
            "A protocol writes the stages, their criteria and the model regimes they "
            "need, so the file states only what belongs to the site. Write the name "
            "alone, or a table carrying it plus the names this file uses for the "
            "parameters and outputs the method moves. Registered: "
            "'matching_hydrographic_network' (Abherve et al., 2023, "
            "doi:10.5194/hess-27-3221-2023). A file that declares its own phases or "
            "objective blocks cannot also name a protocol."
        ),
    )
    method: Annotated[CalibrationMethod | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optimization method. Unset, it follows from what the calibration scores: "
            "'bisection' when it moves one parameter in log space and every one of its "
            "blocks is signed (distance_gap), since the answer is then a zero to find; "
            "'scipy_nelder_mead' otherwise, a cost to minimise. Write it to depart from "
            "that choice, and whenever optimizer_kwargs are given. A phase of "
            "[[calibration.phases]] names its own. "
            "Built-ins: 'grid' (regular sweep, sized by "
            "optimizer_kwargs.points_per_dim), 'random_search', 'bisection' (root of "
            "a signed criterion on one parameter, the stream-network stage), 'optuna' "
            "(TPE), 'cma_es', 'scipy_de', 'scipy_nelder_mead', 'gp_mapping', "
            "'da_mh_gp'. An unknown name is refused when the optimizer is built, "
            "with the list installed here."
            "Optuna is installed by default; install the calibration extra for "
            "cma_es and Optuna's cmaes sampler."
        ),
    )
    evaluator: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "What turns one parameter sample into a cost. Unset runs the HydroModPy "
            "pipeline, which is what every calibrated number in this repository was "
            "produced with. A string and not an enumeration: the values that resolve "
            "depend on what is installed beside HydroModPy, which is how a surrogate "
            "or a foreign model is named without a patch. This build also ships "
            "'analytic_bowl', which runs no model and scores a closed-form surface "
            "whose minimum is the midpoint of each parameter's interval: it rehearses "
            "a whole search -- space, optimizer, stopping rule, report -- in "
            "milliseconds, against an answer known in advance."
        ),
    )
    forward_model: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "What produces the simulated observables when the evaluator is the one "
            "that scores a model with the criteria of this file "
            "('scored_forward_model'). The model answers the outputs declared under "
            "[calibration.outputs] and the objective blocks weigh them, so changing a "
            "metric or a weight is a change to this document and never a patch to the "
            "model. A string and not an enumeration: what resolves depends on what is "
            "installed beside HydroModPy, through the "
            "'hydromodpy.calibration.forward_model' entry-point group. Unset runs "
            "'linear_reservoir', the closed-form reservoir this build ships, which is "
            "how a set of criteria is rehearsed before a model is installed. Read by "
            "no other evaluator."
        ),
    )
    max_iter: Annotated[int, Profile.USER] = Field(
        default=100,
        ge=1,
        description="Maximum number of calibration iterations.",
    )
    tolerance: Annotated[PositiveFloat | None, Profile.USER] = Field(
        default=None,
        description=(
            "How precisely the search has to pin a parameter before it stops, as a "
            "relative precision on the parameter itself: 0.01 asks for one per cent, "
            "0.1 for ten. On a log-transformed parameter that is a ratio, which is "
            "how a conductivity is known in the first place, and it holds wherever the "
            "value sits; on any other transform there is no scale on the value to be "
            "relative to before the search has one, so it reads as a fraction of the "
            "declared interval. Each engine's own stopping option is written from it, "
            "so the same number survives a change of engine, and the engine's own "
            "option stays available for reproducing a published call verbatim. Unset, "
            "the engine's default applies. An engine that stops on its budget rather "
            "than on a precision refuses this rather than ignore it."
        ),
    )
    batch_size: Annotated[int, Profile.DEV] = Field(
        default=1,
        ge=1,
        description="Number of suggestions drawn per ask (for parallel optimizers).",
    )
    parallel: Annotated[int, Profile.DEV] = Field(
        default=1,
        ge=1,
        description=(
            "Number of trials evaluated concurrently inside one batch via a "
            "thread pool. parallel=1 keeps the legacy sequential loop."
        ),
    )
    reject_water_budget_above: Annotated[float | None, Profile.USER] = Field(
        default=None,
        ge=0.0,
        description=(
            "Percent water-balance discrepancy past which a trial is rejected instead "
            "of scored. The solver reports the figure on every run; unset, it is "
            "recorded and nothing acts on it, so a run at twelve per cent is ranked "
            "beside one that closed even though part of the water it routed came from "
            "nowhere. There is no default because there is no universal value: a steady "
            "solve on a coarse mesh closes to a fraction of a per cent, a transient one "
            "with a lake and a routed network legitimately sits higher."
        ),
    )
    warmup_periods: Annotated[int, Profile.USER] = Field(
        default=0,
        ge=0,
        description=(
            "Spin-up (burn-in) periods excluded from every objective block. The first "
            "warmup_periods of each observed/simulated series are dropped before the "
            "metric, so the window where the state still depends on the initial condition "
            "does not bias the calibration. Default 0 (no exclusion). Size it by "
            "increasing it until the objective stops changing (initial-condition "
            "insensitivity), not a fixed guess."
        ),
    )
    scoring_window: Annotated[CalibScoringWindow | None, Profile.USER] = Field(
        default=None,
        description=(
            "Dates bounding the samples every metric is computed on. Mutually "
            "exclusive with warmup_periods, which counts samples instead of dates."
        ),
    )
    phases: Annotated[list[CalibPhaseDecl] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Stages run one after the other, each calibrating its own parameters and "
            "freezing them for the next. Declaring this table is what switches the "
            "runner to staged mode; without it nothing changes for an existing "
            "configuration. The default is None and not an empty list on purpose: the "
            "resume lock hashes the configuration with exclude_none, so an absent "
            "table leaves that hash untouched and checkpoints stay resumable."
        ),
    )
    reuse_completed_phases: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Read a phase's frozen values back from a session that already completed "
            "it in the resumed chain, instead of solving the phase again. What it "
            "reuses: the physical values of the best trial that session's own record "
            "shows for that phase's parameters. What it risks: a session whose model, "
            "mesh or input files differed produced those values for a different "
            "problem, so a reuse is only taken when the session's recorded "
            "params_hash can be reproduced under this run's own cache context; a "
            "mismatch solves the phase again instead of trusting it. Off by default: "
            "re-solving is always correct, reusing without that proof is not."
        ),
    )
    seed: Annotated[int | None, Profile.USER] = Field(
        default=None,
        description="Random seed for reproducibility.",
    )
    save_runs: Annotated[SaveRunsMode, Profile.USER] = Field(
        default="none",
        description=(
            "How much to persist per iteration:\n"
            "- 'none': 1 DuckDB row per iteration, no Zarr.\n"
            "- 'best_n': same + promote top N to full simulations after the loop.\n"
            "- 'all': every iteration becomes a full simulation (Zarr included)."
        ),
    )
    save_best_n: Annotated[int, Profile.USER] = Field(
        default=10,
        ge=0,
        description="Number of top iterations to promote when save_runs='best_n'.",
    )
    use_cache: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Enable params_hash content-addressable cache.",
    )
    lightweight_extraction: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Skip Parquet/Zarr writes for lumped models (GR4J, ...) and "
        "read simulated series from the per-trial RAM cache instead. Only the "
        "promoted runs go through the catalog write path.",
    )
    objective: Annotated[MetricKind, Profile.USER] = Field(
        default="nse",
        description="Metric scoring the single simulated series, when no objective "
        "block is declared. Same vocabulary as a block's 'metric'; typed here so a "
        "bad value is reported against the key that was written.",
    )
    variable: Annotated[str, Profile.USER] = Field(
        default="head",
        description="Observed variable (for ObservationSet).",
    )
    observed_station_id: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Observed station whose cost the optimizer minimises. Every loaded gauge is already scored at its own mesh cell, on the discharge routed to that cell, and every cost is reported; naming one says which of them drives the search. Required when several stations are loaded, optional with one.",
    )
    optimizer_kwargs: Annotated[dict[str, Any], Profile.DEV] = Field(
        default_factory=dict,
        description="Extra keyword arguments forwarded to the optimizer adapter. They "
        "belong to one engine, so a calibration that gives them names its method.",
    )
    parameters: Annotated[dict[str, CalibParameterDecl], Profile.USER] = Field(
        default_factory=dict,
        description="Per-parameter declarations (bounds, transform, prior, path).",
    )
    outputs: Annotated[dict[str, CalibOutputDecl], Profile.USER] = Field(
        default_factory=dict,
        description="Named observables extracted from each candidate run.",
    )
    objective_blocks: Annotated[list[CalibObjectiveBlockDecl], Profile.USER] = Field(
        default_factory=list,
        description="Weighted blocks making up a composite objective. When empty, "
        "a single implicit block is built from 'objective' and 'variable'.",
    )
    persist_iteration_detail: Annotated[PersistIterationDetail, Profile.DEV] = Field(
        default="summary",
        description="'none' skips component metrics; 'summary' keeps block totals; "
        "'full' also stores per-block raw and normalized costs.",
    )
    persist_model_distribution: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Persist the candidate distribution alongside the session.",
    )
    rerun_best_with_outputs: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Replay the best candidate with full outputs after the loop.",
    )
    materialize_candidates: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Write a standalone override TOML for each candidate under "
        "'candidates_root' so runs can be replayed later.",
    )
    candidates_root: Annotated[PurePosixPath | None, Profile.DEV] = Field(
        default=None,
        description="Directory for per-candidate overlay TOMLs. "
        "Required when materialize_candidates is True.",
    )
    aggregate: Annotated[CalibAggregateDecl, Profile.USER] = Field(
        default_factory=CalibAggregateDecl,
        description="How several scored targets become one cost: what made them "
        "comparable, how nested gauges are read, and what one unscorable member does.",
    )
    uncertainty: Annotated[CalibUncertaintyDecl, Profile.USER] = Field(
        default_factory=CalibUncertaintyDecl,
        description="How wide the search reports its own answer to be. The calibrated "
        "value is unaffected; this only decides the interval printed beside it. It is "
        "the default of every phase, and a phase may write its own keys.",
    )
    persistence: Annotated[PersistenceConfig, Profile.USER] = Field(
        default_factory=PersistenceConfig,
        description="Single switch governing every persistence sink "
        "(catalog, Zarr, Parquet, lockfile) for calibration outputs.",
    )

    @field_validator("evaluator")
    @classmethod
    def _check_evaluator_resolves(cls, value: str | None) -> str | None:
        """Refuse an evaluator this installation cannot serve, while reading the document.

        Here rather than at the first trial because a file naming an evaluator
        nobody installed is a broken document, and learning that after
        ``prepare_trials`` has run the whole geographic, mesh and data prefix
        costs that prefix.

        ``None`` is not checked: it means "whatever this build defaults to", and a
        default that does not resolve is an environment fault the registry reports
        with its own message.
        """
        if value is None:
            return value
        from hydromodpy.calibration.evaluation import registry as evaluator_registry

        if evaluator_registry.is_registered(value):
            return value
        served = ", ".join(evaluator_registry.list_evaluator_ids()) or "none"
        raise ValueError(
            f"calibration.evaluator names {value!r}, and this installation serves {served}. "
            f"A third-party evaluator joins that list through the "
            f"{evaluator_registry.ENTRY_POINT_GROUP!r} entry-point group, without a patch to "
            "HydroModPy."
        )

    @field_validator("forward_model")
    @classmethod
    def _check_forward_model_resolves(cls, value: str | None) -> str | None:
        """Refuse a model this installation cannot serve, while reading the document.

        Same place and same reason as the evaluator above: a file naming a model
        nobody installed is a broken document, and finding out at the first trial
        costs everything the search set up before it.
        """
        if value is None:
            return value
        import hydromodpy.calibration.evaluation.forward_registry as forward_registry

        if forward_registry.is_registered(value):
            return value
        served = ", ".join(forward_registry.list_model_ids()) or "none"
        raise ValueError(
            f"calibration.forward_model names {value!r}, and this installation serves "
            f"{served}. A third-party model joins that list through the "
            f"{forward_registry.ENTRY_POINT_GROUP!r} entry-point group, without a patch to "
            "HydroModPy."
        )

    @model_validator(mode="after")
    def _check_the_error_weighting_has_something_to_divide_by(self) -> CalibrationConfig:
        """Refuse ``weighting = "error"`` where there is no residual, or no sigma.

        One over sigma divides a residual by what its instrument resolves. An
        efficiency score is not a residual: it is an aggregate already without a
        unit, so there is nothing to divide. And sigma comes from an observation,
        which means a loaded record: a vector typed into the file carries no error
        model and never will.
        """
        if self.aggregate.weighting != "error":
            return self
        from hydromodpy.calibration.criteria import criterion_for

        for block in self.objective_blocks:
            try:
                needs = criterion_for(str(block.metric)).requirements()
            except ValueError:
                continue
            if needs.cost_is_dimensionless:
                raise ValueError(
                    f'[calibration.aggregate].weighting = "error" divides a residual by '
                    f"what its instrument resolves, and block {block.name!r} is scored on "
                    f"{block.metric!r}, an aggregate that is already a pure number. Score "
                    'it on a residual metric, or set weighting = "manual" and say the '
                    "shares in 'weight'."
                )
        if self.outputs and not any(
            getattr(decl, "observes", None) for decl in self.outputs.values()
        ):
            raise ValueError(
                '[calibration.aggregate].weighting = "error" needs an error model, which '
                "comes from a loaded record: name a station in an output's 'observes'. A "
                "vector written as 'observed_values' carries none."
            )
        return self

    @model_validator(mode="after")
    def _check_the_costs_can_be_added(self) -> CalibrationConfig:
        """Refuse a weighted sum whose members are not in the same unit.

        ``normalize_cost`` exists for exactly this: it divides a block's cost by a
        reference scale so two blocks become comparable. Nothing enforced it, so a
        file could weight a head RMSE in metres at 0.5 and a discharge RMSE in
        m3/s at 0.5, believe it had split the cost evenly, and hand the metres
        whatever share their own magnitude happened to buy.

        The criterion declares whether its cost carries a unit; the outputs a
        block reads say which unit that is. A member is addable when it is
        dimensionless or normalised, and a sum of two that are neither, in
        different families, is refused.
        """
        from hydromodpy.calibration.criteria import criterion_for

        if len(self.objective_blocks) < 2:
            return self
        raw: dict[str, tuple[str, ...]] = {}
        for block in self.objective_blocks:
            if block.normalize_cost:
                continue
            try:
                needs = criterion_for(str(block.metric)).requirements()
            except ValueError:
                continue
            if needs.cost_is_dimensionless:
                continue
            families = tuple(
                sorted(
                    {
                        str(getattr(self.outputs[name], "variable", ""))
                        for name in block.uses_outputs
                        if name in self.outputs
                    }
                )
            )
            raw[str(block.name)] = families
        distinct = {families for families in raw.values() if families}
        if len(distinct) > 1:
            listed = "; ".join(
                f"{name!r} on {', '.join(families)}" for name, families in sorted(raw.items())
            )
            raise ValueError(
                f"these blocks add costs that carry different units: {listed}. The sum "
                "would let the unit set the weighting instead of 'weight'. Declare "
                "normalize_cost = true on each of them, or score them on a metric whose "
                "cost is already a pure number."
            )
        return self

    @model_validator(mode="after")
    def _name_the_engine_the_options_belong_to(self) -> CalibrationConfig:
        """Refuse optimizer_kwargs on a section that names no method.

        Same reason as on a phase: the options belong to one engine, and the one a
        section gets when it names none follows from its criteria.
        """
        if self.optimizer_kwargs and self.method is None:
            raise ValueError(_OPTIONS_WITHOUT_AN_ENGINE.format(where="[calibration]"))
        return self

    @model_validator(mode="after")
    def _check_the_protocol_was_expanded(self) -> CalibrationConfig:
        """Refuse a protocol whose stages nobody wrote.

        The expansion reads the whole configuration document, because the stages
        it writes carry regime and time-grid overrides. Validating
        ``[calibration]`` on its own cannot see it, and a protocol left
        unexpanded would calibrate nothing while the file says it runs a
        published method.
        """
        if self.protocol is not None and not self.phases:
            raise ValueError(
                f"[calibration].protocol = {self.protocol.name!r} declares a method whose "
                "stages were never written. The protocol is read from the whole "
                "configuration document, so load the file through "
                "HydroModPyConfig.from_toml or `hmp calibrate`, not by validating "
                "[calibration] alone."
            )
        return self

    def validate_registry(self) -> None:
        """Verify the method this calibration runs is registered and its kwargs validate.

        The discriminated union :data:`CalibrationMethodConfig` raises eagerly
        when ``optimizer_kwargs`` carries keys foreign to ``method`` so the
        failure happens at config-load time instead of inside the adapter
        constructor. A method left unwritten is checked as :meth:`method_for`
        chooses it.
        """
        from hydromodpy.calibration.optim.method_config import validate_method_kwargs
        from hydromodpy.calibration.optim.optimizer import available_optimizers

        method, _reason = self.method_for()
        available = available_optimizers()
        if method not in available:
            raise ValueError(
                f"Unknown calibration method {method!r}. Available methods: {available}"
            )
        validate_method_kwargs(method, self.optimizer_kwargs)

    def method_for(self, phase: CalibPhaseDecl | None = None) -> tuple[str, str | None]:
        """Return the method this calibration, or one of its phases, runs, and why.

        A method the file writes comes back as written, with no reason. One it
        leaves unwritten is chosen from what the search scores, by
        ``optim.optimizer.choose_method``, and the reason says why. ``phase``
        reads the parameters that phase moves and the blocks it scores, selected
        as the staged runner selects them; ``None`` reads the whole section.
        """
        written = self.method if phase is None else phase.method
        if written is not None:
            return written, None
        from hydromodpy.calibration.optim.optimizer import choose_method

        moved = self.parameters if phase is None else phase.parameters
        transforms = {
            name: str(self.parameters[name].transform) for name in moved if name in self.parameters
        }
        choice = choose_method(transforms, self._criteria_scored_by(phase))
        return choice.method, choice.reason

    def uncertainty_for(self, phase: CalibPhaseDecl | None = None) -> CalibUncertaintyDecl:
        """Return the uncertainty a search reads: the phase's keys over the section's.

        ``None`` reads the section alone. A phase that names another method than
        the section does not inherit the section's ``restarts`` or
        ``perturbation``, which belong to the section's method.
        """
        own = None if phase is None else phase.uncertainty
        if own is None:
            return self.uncertainty
        written = own.model_dump(exclude_none=True)
        merged = self.uncertainty.model_dump()
        if written.get("method", self.uncertainty.method) != self.uncertainty.method:
            merged["restarts"] = None
            merged["perturbation"] = None
        merged.update(written)
        return CalibUncertaintyDecl.model_validate(merged)

    def interval_width_for(self, phase: CalibPhaseDecl | None = None) -> Any:
        """Return the width a search reads its interval with, and where it comes from.

        A tolerance or a mode written in the phase wins, then the one written in
        ``[calibration.uncertainty]``. Left unwritten, both follow what the search
        scores, by ``optim.tolerance.choose_interval_width``. ``phase`` reads the
        blocks that phase scores; ``None`` reads the whole section.

        The answer is an ``optim.tolerance.IntervalWidth``. The signature does not
        name it because this module imports ``optim`` only inside a function.
        """
        from hydromodpy.calibration.optim.tolerance import choose_interval_width

        own = None if phase is None else phase.uncertainty

        def written(key: str) -> tuple[Any, str] | None:
            if own is not None and getattr(own, key) is not None:
                return getattr(own, key), "phase"
            if getattr(self.uncertainty, key) is not None:
                return getattr(self.uncertainty, key), "section"
            return None

        return choose_interval_width(
            self._scored_on_network_distances(phase),
            tolerance=written("tolerance"),
            mode=written("mode"),
        )

    def objective_blocks_for(
        self, phase: CalibPhaseDecl | None = None
    ) -> list[tuple[CalibObjectiveBlockDecl, float]]:
        """Return the blocks a phase, or the whole section, scores, each with its weight.

        Selection is :meth:`_blocks_scored_by`, the same a search itself reads.
        The weight is the phase's own share when it names a table ``{block:
        share}``, else the block's declared weight -- unnormalised, the same
        way :class:`optim.objective.CompositeObjective` takes its own weights
        before dividing by their sum. Empty for a single-metric route
        (:attr:`CalibPhaseDecl.is_single_metric`, or the section route when it
        declares no block). ``hmp calibrate --list-phases`` and ``--check``
        read this to say what each block compares with what.
        """
        blocks = self._blocks_scored_by(phase)
        if phase is not None and isinstance(phase.objective_blocks, dict):
            shares = phase.objective_blocks
            return [(block, float(shares[block.name])) for block in blocks if block.name in shares]
        return [(block, float(block.weight)) for block in blocks]

    def _blocks_scored_by(self, phase: CalibPhaseDecl | None) -> list[CalibObjectiveBlockDecl]:
        """Return the blocks a search scores: the phase's, or every declared one.

        A single-metric phase scores no block.
        """
        if phase is not None and phase.is_single_metric:
            return []
        blocks = self.objective_blocks
        if phase is not None and phase.objective_blocks:
            blocks = [block for block in blocks if block.name in phase.objective_blocks]
        return list(blocks)

    def _criteria_scored_by(self, phase: CalibPhaseDecl | None) -> list[str]:
        """Return the criterion of each block a search scores.

        A phase scores its single metric, or the blocks it names, or every
        declared block. With no block, the section scores ``objective``.
        """
        if phase is not None and phase.is_single_metric:
            return [str(phase.objective or self.objective)]
        blocks = self._blocks_scored_by(phase)
        return [str(block.metric) for block in blocks] or [str(self.objective)]

    def _scored_on_network_distances(self, phase: CalibPhaseDecl | None) -> bool:
        """Whether a search is scored only by network distances left in metres.

        Read as :meth:`_criteria_scored_by` reads the criteria: a single-metric
        phase scores its own ``objective`` or the section's, and a search with
        no block scores the section's ``objective``. A block with a transform is
        no longer in metres. A distance cannot be normalised, so that case does
        not arise, and the single-metric route has no transform.
        """
        from hydromodpy.calibration.criteria.registry import NETWORK_ESTIMATORS

        if phase is not None and phase.is_single_metric:
            return str(phase.objective or self.objective) in NETWORK_ESTIMATORS
        blocks = self._blocks_scored_by(phase)
        if not blocks:
            return str(self.objective) in NETWORK_ESTIMATORS
        return all(
            str(block.metric) in NETWORK_ESTIMATORS and block.transform == "identity"
            for block in blocks
        )

    @field_validator("candidates_root", mode="before")
    @classmethod
    def _normalize_candidates_root(cls, value: Any) -> PurePosixPath | None:
        """Keep user-provided TOML paths stable across host OS path flavors."""
        if value is None:
            return None
        if isinstance(value, PurePosixPath):
            return value
        if isinstance(value, Path):
            return PurePosixPath(value.as_posix())
        return PurePosixPath(str(value).replace("\\", "/"))

    @model_validator(mode="after")
    def _check_phases(self) -> CalibrationConfig:
        """Refuse a phase table that cannot run, before the first solve."""
        phases = self.phases or []
        if not phases:
            return self

        seen: list[str] = []
        for phase in phases:
            if phase.name in seen:
                raise ValueError(f"phase {phase.name!r} is declared twice.")
            seen.append(phase.name)

        declared_parameters = set(self.parameters)
        declared_outputs = set(self.outputs)
        declared_blocks = {block.name for block in self.objective_blocks}
        frozen_by: dict[str, str] = {}

        for index, phase in enumerate(phases):
            unknown = sorted(set(phase.parameters) - declared_parameters)
            if unknown:
                raise ValueError(
                    f"phase {phase.name!r} calibrates undeclared parameter(s) {unknown}; "
                    f"declared: {sorted(declared_parameters)}."
                )
            for parameter in phase.parameters:
                # A parameter may name its quantity instead of writing a path, and
                # the name is resolved against the project catalogue once the whole
                # configuration is loaded. Until then the parameter's own name is
                # what a phase freezes. Two phases may freeze the same path: the
                # later one moves it again from the earlier value, and its value
                # wins. The staged report names both.
                path = self.parameters[parameter].resolve_target() or f"<{parameter}>"
                if phase.freeze_on_success:
                    frozen_by[path] = phase.name

            unknown_outputs = sorted(set(phase.outputs) - declared_outputs)
            if unknown_outputs:
                raise ValueError(
                    f"phase {phase.name!r} scores on undeclared output(s) {unknown_outputs}."
                )
            unknown_blocks = sorted(set(phase.objective_blocks) - declared_blocks)
            if unknown_blocks:
                declared = sorted(declared_blocks) or "nothing"
                raise ValueError(
                    f"phase {phase.name!r} uses undeclared objective block(s) {unknown_blocks}; "
                    f"[[calibration.objective_blocks]] declares {declared}."
                )

            if phase.depends_on is not None:
                if phase.depends_on not in seen[:index]:
                    raise ValueError(
                        f"phase {phase.name!r} depends on {phase.depends_on!r}, which is "
                        "not declared before it."
                    )
            if phase.scoring_window is not None and self.warmup_periods:
                raise ValueError(
                    f"phase {phase.name!r} declares a scoring_window while the "
                    "calibration declares warmup_periods; pick one convention."
                )
            for path in phase.overrides:
                if not path or path.startswith(".") or path.endswith("."):
                    raise ValueError(
                        f"phase {phase.name!r} overrides {path!r}, which is not a "
                        "dotted path into the configuration."
                    )
                if path.startswith("calibration."):
                    raise ValueError(
                        f"phase {phase.name!r} overrides {path!r}: a phase declares its "
                        "own search through its own fields, not by rewriting the "
                        "calibration section under itself."
                    )
                owner = frozen_by.get(path)
                if owner is not None:
                    raise ValueError(
                        f"phase {phase.name!r} overrides {path!r}, which phase {owner!r} "
                        "freezes; the calibrated value would be overwritten and nothing "
                        "downstream would say which one the model ran with."
                    )
            if phase.is_single_metric and (phase.outputs or phase.objective_blocks):
                raise ValueError(
                    f"phase {phase.name!r} declares a single-metric objective and also "
                    "selects outputs or objective blocks; the two are scored by "
                    "different routes and only one of them would run. Pick one "
                    "convention."
                )
            if phase.uncertainty is not None:
                try:
                    self.uncertainty_for(phase)
                except ValidationError as exc:
                    reasons = "; ".join(str(item["msg"]) for item in exc.errors())
                    raise ValueError(
                        f"phase {phase.name!r} writes an uncertainty that does not hold "
                        f"once read over [calibration.uncertainty]: {reasons}"
                    ) from None
        return self

    @model_validator(mode="after")
    def _refuse_a_staged_phase_that_never_says_what_it_scores(self) -> CalibrationConfig:
        """Every phase of a staged calibration must name its own scoring route.

        An empty selection reads "every declared block", which is what a lone
        phase wants and what a staged calibration must never do: the second
        stage would then be scored on the criterion the first one was built for.
        On the Nancon that calibrates Sy against the stream-network gap instead
        of the discharge hydrograph, and the run still reports a number.
        """
        phases = self.phases or ()
        if len(phases) < 2:
            return self
        for phase in phases:
            if phase.objective_blocks or phase.is_single_metric:
                continue
            raise ValueError(
                f"phase {phase.name!r} names neither objective_blocks nor a "
                f"variable/objective pair, so it would be scored on every block the "
                f"calibration declares, including the ones the other phases were "
                f"built for. Name the blocks this phase evaluates, or give it its own "
                f"variable and objective."
            )
        return self

    @model_validator(mode="after")
    def _refuse_two_burn_in_conventions(self) -> CalibrationConfig:
        """A window in dates and a count of samples must not both be declared.

        They say the same thing in two units, and the count means a different
        span at every output frequency, so honouring both would make the scored
        span depend on which one the reader noticed.
        """
        if self.scoring_window is not None and self.warmup_periods:
            raise ValueError(
                "declare either scoring_window (dates) or warmup_periods (samples), not both."
            )
        return self

    @model_validator(mode="after")
    def _ensure_implicit_objective_block(self) -> CalibrationConfig:
        """Build an implicit block from (objective, variable) when none is declared."""
        if not self.objective_blocks:
            variable = self.variable
            implicit_output = self.outputs.get(variable)
            if implicit_output is None:
                return self
            implicit = CalibObjectiveBlockDecl(
                name=f"{self.objective}_{variable}",
                metric=self.objective,
                weight=1.0,
                uses_outputs=[variable],
            )
            self.objective_blocks = [implicit]
        return self

    @model_validator(mode="after")
    def _check_a_block_reads_a_support_its_criterion_scores(self) -> CalibrationConfig:
        """Refuse a block whose criterion cannot read what its outputs produce.

        The criterion names the supports it scores, so one answer covers both
        directions of the mismatch: a distance metric pointed at a gauge, and a
        series metric pointed at a network. Neither crashes on its own. The
        first would read two values of a chronicle as two distances, the second
        would score the pair ``(D_so, D_os)`` against an observed vector, and
        both return a number a reader has no way to doubt.
        """
        from hydromodpy.calibration.criteria import criterion_for

        for block in self.objective_blocks:
            try:
                needs = criterion_for(str(block.metric)).requirements()
            except ValueError:
                continue
            readable = set(needs.reads_supports)
            wrong = sorted(
                (name, str(self.outputs[name].support))
                for name in block.uses_outputs
                if name in self.outputs and str(self.outputs[name].support) not in readable
            )
            if wrong:
                listed = ", ".join(f"{name!r} (support {support!r})" for name, support in wrong)
                raise ValueError(
                    f"block {block.name!r} scores {block.metric!r} on {listed}, and that "
                    f"criterion reads {sorted(readable)}. A network output produces the "
                    "pair (D_so, D_os), two distances and no time; every other support "
                    "produces a series. One criterion cannot read both."
                )
        return self

    @model_validator(mode="after")
    def _check_no_output_is_beyond_every_declared_criterion(self) -> CalibrationConfig:
        """Refuse an output no criterion in this file is able to read.

        Runs after the implicit block is built, so the ``(objective, variable)``
        route counts as a declaration. Such an output is extracted at every
        trial and can enter no cost, whatever block one adds: the calibration
        runs, returns a plausible number, and the constraint the file meant to
        apply is absent from it. A network output alone among series metrics is
        the case that made it visible -- it falls through to the single-metric
        head route, which reads none of its fields -- and the verdict comes from
        the criteria rather than from its support being named here.

        An output some declared criterion could read but that no block happens
        to name is left alone. It is a narrower waste and a different fix: a
        phase of a staged run inherits the outputs of the whole file and scores
        the blocks of its own stage, so that shape is built by this package.
        """
        if not self.outputs:
            return self
        from hydromodpy.calibration.criteria import available_criteria, criterion_for

        # With no block, the head route scores (objective, variable): that
        # criterion is the only one in play, and it is the route a lone network
        # output falls through while reading none of its fields.
        declared = [str(block.metric) for block in self.objective_blocks] or [str(self.objective)]
        readable: set[str] = set()
        for metric in declared:
            try:
                readable.update(criterion_for(metric).requirements().reads_supports)
            except ValueError:
                continue
        if not readable:
            return self
        stranded = {
            name: str(output.support)
            for name, output in self.outputs.items()
            if str(output.support) not in readable
        }
        if not stranded:
            return self
        wanted = sorted(
            {
                criterion
                for criterion in available_criteria()
                if set(criterion_for(criterion).requirements().reads_supports)
                & set(stranded.values())
            }
        )
        listed = ", ".join(
            f"{name!r} (support {support!r})" for name, support in sorted(stranded.items())
        )
        raise ValueError(
            f"the output(s) {listed} can be read by none of the criteria this calibration "
            f"declares, which score {sorted(readable)}. They are computed at every trial "
            f"and weigh nothing. Declare a block on them with one of: {', '.join(wanted)}."
        )

    @model_validator(mode="after")
    def _check_uses_outputs_reference_declared(self) -> CalibrationConfig:
        if not self.objective_blocks:
            return self
        declared = set(self.outputs)
        if not declared:
            return self
        for block in self.objective_blocks:
            unknown = [name for name in block.uses_outputs if name not in declared]
            if unknown:
                raise ValueError(
                    f"objective_block {block.name!r} uses_outputs={unknown!r} "
                    f"but those names are not declared in [calibration.outputs]. "
                    f"Declared outputs: {sorted(declared)}."
                )
        return self

    @model_validator(mode="after")
    def _check_candidates_root_required(self) -> CalibrationConfig:
        if self.materialize_candidates and self.candidates_root is None:
            raise ValueError("materialize_candidates=True requires candidates_root to be set.")
        return self


__all__ = [
    "CalibrationConfig",
    "CalibParameterDecl",
    "CalibOutputDecl",
    "CalibOutputPoint",
    "CalibOutputBoundary",
    "CalibOutputCell",
    "CalibOutputLake",
    "CalibOutputNetwork",
    "CalibPhaseDecl",
    "CalibObjectiveBlockDecl",
    "SaveRunsMode",
    "ParameterMode",
    "OutputSupport",
    "OutputReducer",
    "OutputTime",
    "ObjectiveTransform",
    "PersistIterationDetail",
    "CalibrationMethod",
    "MetricKind",
    "validate_calib_output",
]
