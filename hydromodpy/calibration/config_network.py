"""The matching-network options and the network outputs of a calibration."""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    AfterValidator,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from hydromodpy.calibration.config_terms import (
    GAUGE_ADVICE,
    METRIC_VALUE_DOCS,
    CalibWindow,
    MetricKind,
    ProtocolSteadySpan,
    check_the_method_takes_its_options,
    moved_from,
    renamed,
    renamed_to,
    validated_method_for,
)
from hydromodpy.catchment.stream_network.extent import parse_extent_duration
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import (
    OptionalPath,
    PositiveFloat,
    PositiveInt,
)
from hydromodpy.core.scoring.metric_table import NETWORK_METRIC_NAMES
from hydromodpy.core.scoring.stream_defaults import (
    DEFAULT_VISIBLE_FLOW,
    STREAM_CRITERION_DEFAULTS,
    ObservedRasterization,
    parse_visible_flow,
)
from hydromodpy.core.units.types import Length


class MatchingHydrographicNetworkOptions(HydroModelBase):
    """What a file may say about the protocol beyond naming it.

    Every default here is the value of the publication or a departure the protocol
    declares and prints (``Deviation``). The names are the ones the file uses for
    its own parameters and outputs, and the engines are free: the method is the
    pair of criteria and the order they run in, not the optimizer that walks them.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        **renamed(
            {
                "scoring_window": ("window", "the dates stage two scores"),
                "steady_engine_options": (
                    "steady_method_options",
                    "options of the stage-one method",
                ),
                "transient_engine_options": (
                    "transient_method_options",
                    "options of the stage-two method",
                ),
                "steady_max_iter": ("steady_max_trials", "evaluations stage one may run"),
                "transient_max_iter": ("transient_max_trials", "evaluations stage two may run"),
                "steady_tolerance": (
                    "steady_precision",
                    "how finely stage one pins the conductivity",
                ),
                "transient_tolerance": (
                    "transient_precision",
                    "how finely stage two pins the storage",
                ),
            }
        ),
        "observed_station_id": GAUGE_ADVICE,
    }

    name: Annotated[Literal["matching_hydrographic_network"], Profile.USER] = Field(
        description=(
            "Name of the protocol to run. 'matching_hydrographic_network' is the only "
            "one: a steady stage fits K on the stream network, then a transient stage "
            "fits the storage on a gauge."
        ),
        examples=["matching_hydrographic_network"],
    )
    version: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Recipe version this file was written against. Unset runs the version this "
            "installation carries. Pinned, the file runs what that version writes for "
            "every key of the network output it leaves empty, so a result that informed "
            "a decision stays replayable. A version the installation no longer carries "
            "is refused rather than approximated."
        ),
    )
    conductivity: Annotated[str, Profile.USER] = Field(
        default="K",
        description="Name of the calibration parameter stage one moves, as the file "
        "declares it under [calibration.parameters].",
    )
    storage: Annotated[str | Literal[False], Profile.USER] = Field(
        default="Sy",
        description="Name of the calibration parameter stage two moves. false runs the "
        "network stage alone, which is a method in its own right: it identifies the "
        "conductivity without any discharge record.",
    )
    network_output: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Name of the network output stage one is scored on. Unset picks "
        "the single output declared with support='network'.",
    )
    steady_metric: Annotated[Literal[*NETWORK_METRIC_NAMES], Profile.USER] = Field(
        default="distance_gap",
        description="Criterion of stage one. 'distance_gap' is the signed difference "
        "of Eq. 1, whose zero is the balance the paper solves for. 'distance_mean' is "
        "the mean offset: a diagnostic, and the estimator of the reference script, "
        "whose interior minimum sits nowhere in particular.",
    )
    steady_method: Annotated[
        str,
        Profile.USER,
        AfterValidator(validated_method_for("calibration.protocol.steady_method")),
    ] = Field(
        default="bisection",
        description=(
            "Engine of stage one. The signed criterion crosses zero once over "
            "several decades, which is what a root search wants; any registered engine is "
            "accepted. An unknown name is refused when the file is read, "
            "with the names this installation serves."
        ),
    )
    steady_max_trials: Annotated[PositiveInt | Literal["auto"], Profile.USER] = Field(
        default="auto",
        json_schema_extra=field_metadata(
            renamed_from=["calibration.protocol.steady_max_iter"], unit="-"
        ),
        description="Evaluation budget of stage one. 'auto' lets an engine that counts "
        "its evaluations size it: the bisection budgets its worst case, S + 2E + "
        "ceil(log2(1 / t)) for a root found after its E bracket expansions, 23 on "
        "[1e-7, 1e-3] m/s with seven sweep points and one per cent; any other engine "
        "gets 100. A number below the bisection's nominal count, S + ceil(log2(s / t)) "
        "for a root inside the bounds (15 there), is refused before the first solve.",
    )
    steady_precision: Annotated[PositiveFloat | None, Profile.USER] = Field(
        default=None,
        description="How precisely stage one has to pin the conductivity before it "
        "stops, as a relative precision on the conductivity: 0.01 is the paper's one "
        "per cent. Unset takes the engine's default, which for the bisection is that "
        "same one per cent.",
        json_schema_extra=field_metadata(
            unit="-", renamed_from=["calibration.protocol.steady_tolerance"]
        ),
    )
    steady_method_options: Annotated[dict[str, Any], Profile.USER] = Field(
        default_factory=dict,
        description="Options of the stage-one method, named as that method names "
        "them: for the bisection, sweep_points, bracket_expand, rel_tol and "
        "signed_component. Which ones exist depends on steady_method; a key the "
        "method does not know is refused when the file loads. Used to reproduce a "
        "published call; a precision is said once, in steady_precision.",
        json_schema_extra=field_metadata(
            renamed_from=["calibration.protocol.steady_engine_options"]
        ),
    )
    steady_window: Annotated[ProtocolSteadySpan | None, Profile.USER] = Field(
        default=None,
        description="Dates the steady stage averages, as {start, end}, both ISO 8601 "
        "and both required. A date that does not parse is refused when the file is "
        "read. Unset takes the whole [simulation.time] window.",
    )
    transient_metric: Annotated[MetricKind, Profile.USER] = Field(
        default="nse_log",
        description="Criterion of stage two. The default weights recessions as heavily "
        "as peaks, which is where storage shows.",
        json_schema_extra={"value_docs": METRIC_VALUE_DOCS},
    )
    transient_method: Annotated[
        str,
        Profile.USER,
        AfterValidator(validated_method_for("calibration.protocol.transient_method")),
    ] = Field(
        default="scipy_nelder_mead",
        description=(
            "Search method of stage two, named as calibration.method names one, such "
            "as 'scipy_nelder_mead'. An unknown name is refused when the file is read, "
            "with the names this installation serves."
        ),
    )
    transient_max_trials: Annotated[int, Profile.USER] = Field(
        default=120,
        ge=1,
        description="Evaluation budget of stage two. The simplex cannot count what it "
        "needs, so it gets no extension: a stage two that spends this before it "
        "reaches its precision is reported as not converged, and a re-run with a larger budget "
        "replays the trials already solved from the cache.",
        json_schema_extra=field_metadata(
            unit="-", renamed_from=["calibration.protocol.transient_max_iter"]
        ),
    )
    transient_precision: Annotated[PositiveFloat | None, Profile.USER] = Field(
        default=None,
        description="How precisely stage two has to pin the storage before it stops, "
        "as a relative precision on the storage coefficient.",
        json_schema_extra=field_metadata(
            unit="-", renamed_from=["calibration.protocol.transient_tolerance"]
        ),
    )
    transient_method_options: Annotated[dict[str, Any], Profile.USER] = Field(
        default_factory=dict,
        description="Options of the stage-two method, named as that method names "
        "them, and refused when the file loads if it does not know them. Which ones "
        "exist depends on transient_method.",
        json_schema_extra=field_metadata(
            renamed_from=["calibration.protocol.transient_engine_options"]
        ),
    )
    discharge_variable: Annotated[str, Profile.USER] = Field(
        default="discharge",
        description="Observed variable stage two is scored on.",
    )
    window: Annotated[CalibWindow | None, Profile.USER] = Field(
        default=None,
        description="Dates bounding the samples stage two scores on, as {start, end} in "
        "ISO 8601, either one optional. A date that does not parse is refused when the "
        "file is read. Unset, "
        "stage two scores the window of [metrics] when the file writes one, and "
        "otherwise from one year after [simulation.time].start_datetime: the first "
        "year is spin-up. A window on [calibration] replaces "
        "both. A run of one year or less is scored whole. Write start = the run's own "
        "start to score the spin-up year too.",
        json_schema_extra=field_metadata(renamed_from=["calibration.protocol.scoring_window"]),
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_the_bare_name(cls, data: Any) -> Any:
        """``protocol = "matching_hydrographic_network"`` is the whole declaration."""
        if isinstance(data, str):
            return {"name": data}
        return data

    @field_validator("storage", mode="before")
    @classmethod
    def _no_storage_is_written_false(cls, value: object) -> object:
        """Hold the network stage alone as ``False``, whichever way it was said.

        A dump drops a ``None``, and an absent key reloads as the default, so a
        run sealed in this mode would come back with two stages. ``False`` is
        what TOML can write, and it survives the round trip.
        """
        return False if value is None else value

    @model_validator(mode="after")
    def _check_each_stage_method_takes_its_options(self) -> MatchingHydrographicNetworkOptions:
        """Refuse a stage option its method does not take, under the key the file wrote.

        The phase the protocol writes would refuse it too, but under the name of
        a phase the file never wrote.
        """
        for stage in ("steady", "transient"):
            check_the_method_takes_its_options(
                "[calibration.protocol]",
                getattr(self, f"{stage}_method"),
                getattr(self, f"{stage}_method_options"),
                key=f"{stage}_method_options",
            )
        return self

    def stage_options_run_as_their_method_does(self) -> frozenset[str]:
        """Return the stage options written to what their method runs anyway.

        The recipe leaves a stage's method options and its precision to the
        method. ``steady_method_options = {sweep_points = 7}`` or
        ``steady_precision = 0.01`` beside a bisection, whose defaults are seven
        points and one per cent, restate the recipe and do not move off it.
        """
        from hydromodpy.calibration.optim.method_config import (
            default_relative_precision,
            method_options_are_its_defaults,
        )

        same: set[str] = set()
        for stage in ("steady", "transient"):
            method = str(getattr(self, f"{stage}_method"))
            options = dict(getattr(self, f"{stage}_method_options") or {})
            if options and method_options_are_its_defaults(method, options):
                same.add(f"{stage}_method_options")
            precision = getattr(self, f"{stage}_precision")
            if precision is not None and default_relative_precision(method, options) == float(
                precision
            ):
                same.add(f"{stage}_precision")
        return frozenset(same)


class CalibNetworkBoundWeights(HydroModelBase):
    """How the two maps of a network output share one calibrated value.

    A root search closes one root per map and returns the weighted geometric
    mean, ``log K = permanent * log K*_permanent + complete * log K*_complete``.
    A minimiser has no root to combine and minimizes
    ``permanent * |J_permanent| + complete * |J_complete|`` instead, which tends
    to land on one of the two roots rather than between them.
    """

    permanent: Annotated[float, Profile.USER] = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Weight of the permanent map, scored against the minimal mask.",
        json_schema_extra={"unit": "-"},
    )
    complete: Annotated[float, Profile.USER] = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Weight of the complete map, scored against the maximal mask.",
        json_schema_extra={"unit": "-"},
    )

    @model_validator(mode="after")
    def _sum_to_one(self) -> CalibNetworkBoundWeights:
        """Refuse weights that do not sum to one: they interpolate between two roots."""
        total = float(self.permanent) + float(self.complete)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"calibrate_on sums to {total:g} (permanent = {self.permanent:g}, complete = "
                f"{self.complete:g}). The two weights place the returned value between the two "
                "roots in log space, so they must sum to one."
            )
        return self


class CalibNetworkHeads(HydroModelBase):
    """Where a mapped stream head may land, read only under ``drawn_by = 'heads'``."""

    radius: Annotated[Length, Profile.USER] = Field(
        default=STREAM_CRITERION_DEFAULTS.heads_snap_radius_m,
        description="The largest distance, a length (a bare number is in metres), between a "
        "mapped stream head and the centre of the cell it lands on. A head with no landing "
        "cell that close is lost, draws nothing and is counted in n_heads_lost.",
        json_schema_extra=moved_from("heads_snap_radius"),
    )
    min_drained_area: Annotated[float, Profile.USER] = Field(
        default=STREAM_CRITERION_DEFAULTS.heads_min_drained_area_km2,
        ge=0.0,
        description="The drained area a cell needs before a head may land on it, so a head "
        "next to its valley lands in the valley and not on the ridge cell beside it.",
        json_schema_extra=moved_from("heads_min_drained_area_km2", unit="km2"),
    )

    @field_validator("radius")
    @classmethod
    def _positive_radius(cls, value: object) -> object:
        """Refuse a snap radius that is zero or negative."""
        magnitude = float(value.to("m").magnitude)  # type: ignore[union-attr]
        if not magnitude > 0.0:
            raise ValueError(f"radius = {magnitude:g} m: a snap radius is a positive distance.")
        return value


class CalibNetworkMap(HydroModelBase):
    """What is observed: the mapped network, its role in the cost and how it is drawn."""

    complete: Annotated[Literal["data.hydrography"] | OptionalPath, Profile.USER] = Field(
        default=None,
        description="The complete map, every mapped reach: a vector file, read only from "
        "here, or 'data.hydrography', the network the hydrography data family loaded (a "
        "local file or an osm / bdtopage / euhydro download), clipped to the delineated "
        "catchment.",
        json_schema_extra=moved_from("stream_geometry_path", "observed_network", site_scoped=True),
    )
    permanent: Annotated[Literal["data.hydrography"] | OptionalPath, Profile.USER] = Field(
        default=None,
        description="The permanent map, the reaches that flow all year, which the complete "
        "map contains: a vector file, read as it is and never filtered by attribute, or "
        "'data.hydrography', the permanent reaches the hydrography data family wrote beside "
        "its network. A source that does not say which reaches flow all year gives none. "
        "The complete map scored is the union of the two, and the share of this map outside "
        "the complete one is published.",
        json_schema_extra=moved_from("minimal_stream_geometry_path", "minimal_observed_network"),
    )
    calibrate_on: Annotated[
        Literal["permanent", "complete"] | CalibNetworkBoundWeights | None, Profile.USER
    ] = Field(
        default=None,
        description="The role of each map, required when both are declared and refused "
        "otherwise. 'permanent' or 'complete' names the map in the cost. In one state, the "
        "other map is scored at the same state as a validation outside the cost, and "
        "'permanent' is how Abherve et al. (2025) calibrate. With 'model.extent', the named "
        "map has all the weight. A table {permanent = 0.5, complete = 0.5} shares the value "
        "between both bounds, and only 'model.extent' scores two bounds.",
        json_schema_extra=moved_from("extent.weights"),
    )
    drawn_by: Annotated[ObservedRasterization, Profile.USER] = Field(
        default=STREAM_CRITERION_DEFAULTS.observed_rasterization,
        description="How the map is drawn on the mesh cells. 'crossing' "
        "keeps the cell holding each point where a line crosses the segment joining two "
        "edge-sharing cell centres. On a structured grid it reproduces WhiteboxTools "
        "VectorLinesToRaster, the paper's tool, and draws the map one cell wide like "
        "the simulated network, so a model that matches the map scores J = 0. 'touch' "
        "keeps every cell the line touches, corners included, and replays a session "
        "made before 2026-09; it thickens every diagonal step of the map and departs "
        "from the paper. 'heads' keeps only the free ends of the map whose largest "
        "drained area within 'heads.radius' does not exceed that of the other end of "
        "their reach, lands each on a nearby cell and draws the "
        "rest down the criterion's own descent: the field ditches and rectified reaches "
        "below a head stop counting as model error, and the drawn map reaches the "
        "outlet. Keep 'crossing' for a map that is not a tree: canals, braids, polders, "
        "karst.",
        json_schema_extra=moved_from("observed_rasterization"),
    )
    heads: Annotated[CalibNetworkHeads | None, Profile.USER] = Field(
        default=None,
        description="Where a head may land, read only under drawn_by = 'heads' and refused "
        "under another rule. Left out under 'heads', the defaults of its keys.",
    )
    clip_to_catchment: Annotated[bool, Profile.USER] = Field(
        default=STREAM_CRITERION_DEFAULTS.clip_map_to_catchment,
        description="Cut the map to the delineated catchment before drawing it, with the "
        "shape the hydrography data family clips what it loads to, so a file and "
        "'data.hydrography' draw the same map from the same data. Under 'heads' an end the "
        "cut made is no stream head. false reads a file whole and takes every free end as a "
        "candidate head.",
        json_schema_extra=moved_from("clip_map_to_catchment"),
    )
    position_accuracy: Annotated[Length | None, Profile.USER] = Field(
        default=None,
        description="Positional accuracy of the map. It enters the automatic validity length "
        "only, so it is refused beside a 'verdict.validity_length' written as a length: the "
        "cell size h there is max(h_obs, this), because a map is not placed better when the "
        "mesh is refined. r_optim stays D_optim / h_obs, the paper's Eq. 3. Unset is the "
        "literal reading of the paper.",
        json_schema_extra=moved_from("observed_position_accuracy"),
    )

    @field_validator("heads")
    @classmethod
    def _heads_under_their_rule(
        cls, value: CalibNetworkHeads | None, info: ValidationInfo
    ) -> CalibNetworkHeads | None:
        """Fill the heads settings under the heads rule, and refuse them under another."""
        rule = info.data.get("drawn_by")
        if rule == "heads":
            return value or CalibNetworkHeads()
        if value is not None:
            raise ValueError(
                f"map.heads is read only under drawn_by = 'heads', and drawn_by = {rule!r} "
                "never reads it. Drop it, or write drawn_by = 'heads'."
            )
        return value

    @model_validator(mode="after")
    def _say_the_role_of_each_map(self, info: ValidationInfo) -> CalibNetworkMap:
        """Refuse a network with no source, and two maps without their role.

        A sealed run may hold no map: it was scored on a network the DEM derived (no longer offered),
        which is no observation any more, and a replay reads its stored scores.
        """
        if self.complete is None:
            context = info.context if isinstance(info.context, Mapping) else {}
            if context.get("validation_context") == "snapshot":
                return self
            raise ValueError(
                "the network output has no complete map. Write map.complete = "
                "'data.hydrography' or the path of a vector file."
            )
        if self.permanent is not None and self.calibrate_on is None:
            raise ValueError(
                "the network output declares both maps and does not say what it calibrates on. "
                "Write map.calibrate_on = 'permanent', 'complete' or, with model.extent, "
                "{permanent = 0.5, complete = 0.5}."
            )
        if self.permanent is None and self.calibrate_on is not None:
            raise ValueError(
                "map.calibrate_on gives a role to two maps and only the complete map is "
                "declared. Declare map.permanent or drop map.calibrate_on."
            )
        return self

    def files(self) -> dict[str, Path]:
        """Return the maps named by a file, by field: what a caller anchors or hashes."""
        written = {"complete": self.complete, "permanent": self.permanent}
        return {
            role: Path(value)
            for role, value in written.items()
            if value not in (None, "data.hydrography")
        }

    @property
    def bound_weights(self) -> CalibNetworkBoundWeights:
        """Return the share of each map in the value. With one map it has all of it."""
        if isinstance(self.calibrate_on, CalibNetworkBoundWeights):
            return self.calibrate_on
        if self.calibrate_on == "permanent":
            return CalibNetworkBoundWeights(permanent=1.0, complete=0.0)
        return CalibNetworkBoundWeights(permanent=0.0, complete=1.0)


class CalibNetworkExtent(HydroModelBase):
    """The transient two-bound mode of a network output.

    Declared, the output stops reading one state. For every complete calendar
    year of the run, the maximal simulated mask holds the cells flowing for at
    least ``flowing_at_least``, and the minimal one the cells flowing at every
    timestep but for at most ``dry_at_most``. A cell enters the mask scored when
    it meets the rule in at least ``year_quorum`` of the scored years. Each bound
    is scored once by the distance criterion: the maximal mask against the
    complete map, the minimal mask against the permanent map when one is declared.
    Both durations are converted to whole timesteps with the run's step, so the
    same file means the same on a daily and a monthly run.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "maximal_flowing_steps": renamed_to(
            "maximal_flowing_steps",
            "flowing_at_least",
            "how long a cell has to flow in a year, with its unit, such as '1 month'",
        ),
        "minimal_dry_steps": renamed_to(
            "minimal_dry_steps",
            "dry_at_most",
            "how long a cell may be dry in a year, with its unit, such as '1 month'",
        ),
        **renamed(
            {
                "maximal_flowing_duration": (
                    "model.extent.flowing_at_least",
                    "how long a cell must flow",
                ),
                "minimal_dry_duration": (
                    "model.extent.dry_at_most",
                    "how long a cell may be dry in a year",
                ),
                "weights": ("map.calibrate_on", "the role of each map"),
            }
        ),
    }

    flowing_at_least: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="How long a cell has to flow in a year to enter the maximal mask, "
        "with its unit: '30 d', '1 month'. Converted by the run's timestep, rounded up to "
        "whole timesteps and never below one. Left out, one timestep, whatever the step. "
        "At most the shortest complete year, checked on the run.",
        json_schema_extra=moved_from(
            "extent.maximal_flowing_steps", "extent.maximal_flowing_duration"
        ),
    )
    dry_at_most: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="How long a cell may be dry in a year and stay in the minimal mask, "
        "with its unit: '1 d', '1 month'. Converted by the run's timestep and rounded "
        "down to whole timesteps, possibly none: '1 d' is one dry timestep on a daily "
        "run, none on a monthly one. Left out, one timestep, whatever the step. The "
        "year's timesteps minus these have to stay at least the flowing timesteps of "
        "the maximal rule, checked on the run, so the minimal mask sits inside the "
        "maximal one.",
        json_schema_extra=moved_from("extent.minimal_dry_steps", "extent.minimal_dry_duration"),
    )
    year_quorum: Annotated[float, Profile.USER] = Field(
        default=0.5,
        gt=0.0,
        le=1.0,
        description="Share of the scored years in which a cell has to meet a bound's rule "
        "to enter it: ceil(year_quorum * n_years) years. Warned under three scored years, "
        "where one half is a union of two.",
        json_schema_extra={"unit": "-"},
    )
    visible_flow: Annotated[str, Profile.USER] = Field(
        default=DEFAULT_VISIBLE_FLOW,
        description="Routed discharge a cell of the downstream closure has to carry to "
        "flow: a discharge with its unit ('1 L/s') or a share of the outlet discharge at "
        "the same timestep ('1%'). '0 L/s' is the geometric definition. Never scaled with "
        "the cell size. It exists in this transient mode only: an output read in one state "
        "scores the closure alone. No value is agreed: Zanetti et al. (2024) threshold a "
        "simulated discharge at 10 L/s, field zero-flow thresholds of 1 to 3 L/s are in use.",
    )

    @field_validator("flowing_at_least", "dry_at_most", mode="before")
    @classmethod
    def _readable_duration(cls, value: Any, info: ValidationInfo) -> Any:
        """Refuse a duration the criterion could not read at the first trial."""
        days = parse_extent_duration(value, location=str(info.field_name))
        if days is not None and info.field_name == "flowing_at_least" and not days > 0.0:
            raise ValueError("flowing_at_least must be longer than zero.")
        return value

    @field_validator("visible_flow")
    @classmethod
    def _readable_visible_flow(cls, value: str) -> str:
        """Refuse a threshold the criterion could not read at the first trial."""
        parse_visible_flow(value)
        return value


class CalibNetworkModel(HydroModelBase):
    """How the model draws its own stream network."""

    seepage_threshold: Annotated[float, Profile.USER] = Field(
        default=STREAM_CRITERION_DEFAULTS.tau_specific_ratio,
        ge=0.0,
        description="A cell releasing less than this fraction of the mean basin recharge, taken "
        "over its own area, is not a seepage face. Zero reproduces the purely geometric criterion of the "
        "paper. Frozen over the whole search: a threshold moving with the trial would "
        "cost the criterion its monotonicity.",
        json_schema_extra=moved_from("tau_specific_ratio", unit="-"),
    )
    neighbours: Annotated[Literal["D8", "D4"], Profile.USER] = Field(
        default="D8" if STREAM_CRITERION_DEFAULTS.diagonal_neighbors else "D4",
        description="The graph the descent walks. 'D8' descends over shared nodes, the eight "
        "neighbours of a quad mesh, and is the paper: its distances are traced by "
        "WhiteboxTools on a D8 pointer, and the delineation that produced the catchment uses "
        "one too. 'D4' descends over shared edges only and departs from the paper. It is "
        "not a second-decimal choice: on a synthetic valley whose talweg runs along the "
        "grid diagonal, the most accumulated cell collects 100 per cent of the domain "
        "over shared nodes and 6.6 per cent over shared edges. On a mesh whose faces are "
        "not all quadrilaterals no cell has a diagonal and the descent walks shared "
        "edges either way; on a Voronoi mesh the two graphs are the same one.",
        json_schema_extra=moved_from("diagonal_neighbors"),
    )
    weighting: Annotated[Literal["cell", "area"], Profile.USER] = Field(
        default="cell",
        description="Average one cell one vote (the paper) or weighted by cell area. "
        "Both values are always reported; use 'area' on a mesh refined along the "
        "streams, where cell density is highest exactly where distances are smallest.",
        json_schema_extra={
            **moved_from("weighting"),
            "value_docs": {
                "cell": "Every cell counts once in the average, as in the paper.",
                "area": "Every cell counts in proportion to its area.",
            },
        },
    )
    extent: Annotated[CalibNetworkExtent | None, Profile.USER] = Field(
        default=None,
        description="The transient two-bound mode. Unset, the output reads one state, the "
        "method of the papers. Set, it reads every timestep of a transient run and scores "
        "the maximal simulated mask against the complete map and, when 'map.permanent' is "
        "declared, the minimal mask against the permanent map. Refused on a run with a "
        "single period or no complete calendar year.",
        json_schema_extra=moved_from("extent"),
    )


class CalibNetworkVerdict(HydroModelBase):
    """When the result of a network output is qualified or refused."""

    max_catchment_mismatch: Annotated[
        Annotated[float, Field(ge=0.0)] | Literal[False], Profile.USER
    ] = Field(
        default=STREAM_CRITERION_DEFAULTS.max_catchment_mismatch,
        description="Largest gap allowed between the scored catchment and the delineated "
        "one, as a share of the delineated area: 'catchment_mismatch', the area of their "
        "symmetric difference over the area of the outline the mesh followed. It depends on "
        "the geometry alone, so it is read once, before the first solve, and a gap above it "
        "refuses the search. A large gap means an outlet on another branch, or a mesh too "
        "coarse for the catchment. false never refuses, and the gap is still published on "
        "every trial. A synthetic domain has no delineated catchment and is never refused.",
        json_schema_extra={"unit": "-"},
    )
    validity_length: Annotated[Literal["auto"] | Length, Profile.USER] = Field(
        default="auto",
        description="Validity bound of Eq. 4, a length: the calibration is valid when "
        "D_optim <= this. 'auto' is 2 h, the paper's two cells, where h is h_obs, the cell "
        "size on the mapped network, raised to 'map.position_accuracy' if that is "
        "declared. A length such as '150 m' is used as it is. The bound qualifies the "
        "result and never penalises the cost.",
        json_schema_extra=moved_from("validity_length"),
    )
    on_invalid: Annotated[Literal["warn", "error"], Profile.USER] = Field(
        default="warn",
        description="What a violation of Eq. 4 does: D_optim above 'validity_length'. The "
        "bound is read once, on the trial the search returns, as the paper reads it at the "
        "optimum, and on each bound in the cost of the two-bound mode; every trial still "
        "records 'r_optim', 'r_optim_valid' and 'validity_length_m'. 'warn' logs it and "
        "returns the value, because a calibration is asked for a number. 'error' raises "
        "after the session is saved, so a staged calibration freezes nothing and runs no "
        "phase that depends on this one.",
        json_schema_extra=moved_from("on_roptim_violation"),
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
        json_schema_extra=moved_from("alpha_warning_threshold"),
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
        json_schema_extra=moved_from("clipping_warning_share", unit="-"),
    )
    clipping_warning_gap: Annotated[float, Profile.EXPERT] = Field(
        default=STREAM_CRITERION_DEFAULTS.clipping_warning_gap,
        ge=0.0,
        le=1.0,
        description="Minimum absolute gap between the whole-mesh and the catchment "
        "alpha for the clipping report to fire. A linework spilling out of the "
        "catchment over ground that routes the same way leaves the two ratios equal, "
        "and reporting it there would be noise on every ordinary project.",
        json_schema_extra=moved_from("clipping_warning_gap"),
    )

    @field_validator("max_catchment_mismatch", mode="before")
    @classmethod
    def _true_is_no_share(cls, value: object) -> object:
        """Refuse ``true``, which the float of the union would read as a share of one."""
        if value is True:
            raise ValueError(
                "max_catchment_mismatch = true says nothing: write a share such as 0.05, "
                "or false for no refusal."
            )
        if isinstance(value, int) and not isinstance(value, bool) and value == 0:
            # The union would read the integer 0 as false and switch the veto off.
            return 0.0
        return value

    @field_validator("validity_length")
    @classmethod
    def _positive_validity_length(cls, value: object) -> object:
        """Refuse a validity length that is zero or negative."""
        if value == "auto":
            return value
        magnitude = float(value.to("m").magnitude)  # type: ignore[union-attr]
        if not magnitude > 0.0:
            raise ValueError(
                f"validity_length = {magnitude:g} m: a validity length is a positive "
                "distance, or 'auto'."
            )
        return value


class CalibOutputNetwork(HydroModelBase):
    """The mapped stream network as a calibration target.

    The criterion compares a simulated stream network to a mapped one. For
    every cell of the simulated network the descent to the mapped network is
    measured, and reciprocally. The output produces the pair ``(D_so, D_os)``;
    the metric on top of it is ``distance_gap``, their signed difference in
    absolute value, whose zero is the balance between an excess of simulated
    stream and a missing one.

    It can drive any parameter that moves where the water table meets the
    surface. What it identifies depends on what moves: with the homogeneous
    conductivity alone, at fixed geometry and recharge, it identifies ``K/R``,
    the ratio of Abherve et al. (2023), and not ``K`` itself.

    There is no ``observed_values`` here and there cannot be: the criterion
    balances two simulated quantities against each other, so nothing in it is
    fitted to a record. The mapped network enters as a geometry, not as a
    series. Three tables hold the rest: ``map`` is what is observed, ``model``
    how the model draws its network and ``verdict`` when the result holds.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "max_unreachable_fraction": (
            "it bounded a share that is zero by construction, since the outlet is sealed "
            "into the target of D_so. Delete it. What it meant to catch is a surface or an "
            "outlet that does not close on the catchment, and "
            "[calibration.outputs.<name>.verdict] max_catchment_mismatch refuses that, 0.05 "
            "by default."
        ),
        **renamed(
            {
                "stream_geometry_path": ("map.complete", "the file of every mapped reach"),
                "observed_network": ("map.complete", "where every mapped reach comes from"),
                "minimal_stream_geometry_path": (
                    "map.permanent",
                    "the file of the permanent reaches",
                ),
                "minimal_observed_network": (
                    "map.permanent",
                    "where the permanent reaches come from",
                ),
                "observed_rasterization": ("map.drawn_by", "how the map is drawn on the cells"),
                "clip_map_to_catchment": ("map.clip_to_catchment", "whether the map is cut first"),
                "heads_snap_radius": ("map.heads.radius", "how far from its cell a head may land"),
                "heads_min_drained_area_km2": (
                    "map.heads.min_drained_area",
                    "the area a head needs, km2",
                ),
                "observed_position_accuracy": (
                    "map.position_accuracy",
                    "how well the map is placed",
                ),
                "tau_specific_ratio": (
                    "model.seepage_threshold",
                    "what makes a cell a seepage face",
                ),
                "diagonal_neighbors": (
                    "model.neighbours",
                    "the graph the descent walks, 'D8' or 'D4'",
                ),
                "weighting": ("model.weighting", "how the cells count in the average"),
                "extent": ("model.extent", "the transient two-bound mode"),
                "validity_length": ("verdict.validity_length", "the validity bound of Eq. 4"),
                "on_roptim_violation": ("verdict.on_invalid", "what a violation of Eq. 4 does"),
                "alpha_warning_threshold": (
                    "verdict.alpha_warning_threshold",
                    "when alpha warns",
                ),
                "clipping_warning_share": (
                    "verdict.clipping_warning_share",
                    "when clipping is reported",
                ),
                "clipping_warning_gap": (
                    "verdict.clipping_warning_gap",
                    "when clipping is reported",
                ),
            }
        ),
    }

    variable: Annotated[str, Profile.USER] = Field(
        default="release_flux",
        description="Per-cell observable read from the solver, in m3/s, positive "
        "when the aquifer feeds the surface.",
    )
    support: Annotated[Literal["network"], Profile.USER] = Field(
        default="network",
        description="Discriminator: compare a simulated stream network to a mapped one.",
    )
    map: Annotated[CalibNetworkMap, Profile.USER] = Field(
        description="What is observed: the mapped network, its role and how it is drawn.",
    )
    model: Annotated[CalibNetworkModel, Profile.USER] = Field(
        default_factory=CalibNetworkModel,
        description="How the model draws its own stream network.",
    )
    verdict: Annotated[CalibNetworkVerdict, Profile.USER] = Field(
        default_factory=CalibNetworkVerdict,
        description="When the result of this output is qualified or refused.",
    )
    time: Annotated[Literal["last", "first"] | str, Profile.USER] = Field(
        default="last",
        description="Which single state the release flux is read at: 'last' (default), "
        "'first', or an ISO date such as '2002-10-15', which reads the state of the "
        "period that holds it, (start, end]. That state is dated at its period's end, "
        "which is the date a window is compared with. A steady phase runs one "
        "period over its window, so every date of that window reads its one state and "
        "one output serves both regimes. 'all' and a list of dates are refused: a "
        "network output reads one state.",
    )

    @field_validator("time", mode="before")
    @classmethod
    def _check_single_state(cls, value: object) -> object:
        """Refuse a selector that reads more than one state, and read a date.

        The extraction serves ``build_simulated_network``
        (``hydromodpy/catchment/stream_network/network.py``) the one row this names, so 'last',
        'first' and a date are each scored at the state the file names. 'all' or
        a list would name several states for one mask.

        Runs before the field's own type check so this message, not a generic
        type error, is what 'all' or a list of dates gets. A TOML date written
        bare reads as a date and is kept as its ISO spelling.
        """
        if value == "all" or isinstance(value, list):
            raise ValueError(
                f"calibration output for the stream network has time={value!r}: a "
                "network output reads exactly one state, 'last', 'first' or one date. A "
                "transient comparison of the minimal and maximal extents is the "
                "'model.extent' table of the output, not this field."
            )
        if isinstance(value, datetime.date):
            value = value.isoformat()
        if isinstance(value, str) and value not in ("last", "first"):
            try:
                datetime.datetime.fromisoformat(value.strip())
            except ValueError as exc:
                raise ValueError(
                    f"calibration output for the stream network has time={value!r}: write "
                    "'last', 'first' or an ISO date such as '2002-10-15'."
                ) from exc
            return value.strip()
        return value

    @model_validator(mode="after")
    def _say_each_thing_once(self) -> CalibOutputNetwork:
        """Refuse what contradicts the rest of the output across its tables.

        ``time`` names one state, and the two-bound mode reads them all, so only
        its default may stand beside it. A share of two bounds needs the mode that
        scores two. An accuracy only enters the automatic validity length.
        """
        if self.model.extent is not None and self.time != "last":
            raise ValueError(
                f"the network output declares model.extent and time = {self.time!r}. "
                "The two-bound mode reads every timestep of the run; drop 'time'."
            )
        if self.model.extent is None and isinstance(
            self.map.calibrate_on, CalibNetworkBoundWeights
        ):
            raise ValueError(
                "map.calibrate_on shares the value between two bounds and one state has one "
                "cost. Name one map, 'permanent' or 'complete', or declare model.extent."
            )
        if self.map.position_accuracy is not None and self.verdict.validity_length != "auto":
            raise ValueError(
                "map.position_accuracy enters the automatic validity length only, and "
                "verdict.validity_length is written as a length, so nothing reads it. Drop one."
            )
        return self
