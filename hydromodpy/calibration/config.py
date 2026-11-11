"""Pydantic model for the ``[calibration]`` TOML section.

Minimal TOML::

    [calibration]
    method       = "grid"
    max_trials   = 200
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
    max_trials = 80
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

import datetime
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal, TypeAlias

from pydantic import (
    AfterValidator,
    BeforeValidator,
    Field,
    TypeAdapter,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from hydromodpy.catchment.stream_network.extent import parse_extent_duration
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import (
    NonEmptyStr,
    NonNegativeInt,
    OptionalPath,
    PositiveFloat,
    PositiveInt,
    StationName,
)
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.plugin_registry import check_registered_name
from hydromodpy.core.scoring.cost_margin import parse_cost_margin
from hydromodpy.core.scoring.metric_table import (
    METRIC_SENSE,
    METRIC_SPECS,
    NETWORK_METRIC_NAMES,
    TRIAL_METRIC_NAMES,
)
from hydromodpy.core.scoring.stream_defaults import (
    DEFAULT_VISIBLE_FLOW,
    STREAM_CRITERION_DEFAULTS,
    ObservedRasterization,
    parse_visible_flow,
)
from hydromodpy.core.units import Length
from hydromodpy.schema.changes import prerelease_refusal


def renamed_to(old: str, new: str, meaning: str) -> str:
    """Return the refusal of a key that a pre-release of 2.0 wrote under its old name.

    It is a value of ``model_refused_keys``. *meaning* says in one clause what the new
    key is, so a reader who never saw the old name still learns what to write. The
    doctor of a 2.0.x release rewrites the file, which the sentence of
    :func:`hydromodpy.schema.changes.prerelease_refusal` says.
    """
    return f"renamed to {new!r} ({meaning}). {prerelease_refusal(_THIS_TABLE, [old])}"


def _renamed(renames: Mapping[str, tuple[str, str]]) -> dict[str, str]:
    """Return the refusals of keys given as old key: (new key, what it is)."""
    return {old: renamed_to(old, new, meaning) for old, (new, meaning) in renames.items()}


def _never_read(*keys: str) -> dict[str, str]:
    """Return the refusals of keys that a pre-release declared and no step ever read.

    No run depended on such a key, so the file loses nothing when the key goes.
    """
    return {key: "no step ever read it, so delete it from the file." for key in keys}


_THIS_TABLE = "This table"
_GAUGE_ADVICE = (
    "the station is [site] gauge, and a point output names its own with 'observes'. "
    + prerelease_refusal(_THIS_TABLE, ["observed_station_id"])
)


SaveRunsMode = Literal["none", "best_n", "all"]
ParameterMode = Literal["replace", "scale"]
OutputSupport = Literal["point", "boundary", "cell", "lake", "network"]
OutputReducer = Literal["mean", "sum", "last", "none"]
_OUTPUT_REDUCER_VALUE_DOCS: dict[str, str] = {
    "mean": "Scores one value: the mean of the kept values.",
    "sum": "Scores one value: the sum of the kept values.",
    "last": "Scores one value: the last kept value.",
    "none": "Scores every kept value against its observation.",
}
"""What each reducer of a calibration output does to the kept time steps."""
ObjectiveTransform = Literal["identity", "log", "inverse"]
PersistIterationDetail = Literal["none", "summary", "full"]
MetricKind = Literal[*TRIAL_METRIC_NAMES]
"""Metric names a TOML may select: the trial metrics of ``core.scoring.metric_table``."""

_METRIC_VALUE_DOCS: dict[str, str] = {name: METRIC_SPECS[name].doc for name in TRIAL_METRIC_NAMES}
"""What each metric a TOML may select measures, shown beside every key that picks one."""


def _validated_method_for(key: str) -> Callable[[str], str]:
    def _validate(value: str) -> str:
        from hydromodpy.calibration.optim.optimizer import ENTRY_POINT_GROUP, optimizers

        return check_registered_name(
            value,
            names=optimizers.names(),
            key=key,
            group=ENTRY_POINT_GROUP,
        )

    return _validate


CalibrationMethod = Annotated[
    str,
    AfterValidator(_validated_method_for("calibration.method")),
]
"""A calibration method name, one of the optimizers this installation serves.

Validated once, when the file is read, so a typo fails beside the field that wrote
it and not in the depths of an adapter. The shared registry is the single source:
``optimizers.names()`` and the refusal sentence are the ones
:func:`hydromodpy.core.plugin_registry.check_registered_name` prints, and
``da_mh_gp`` is one of the names served.
"""


def _no_list_of_dates(value: Any) -> Any:
    """Refuse a list of dates as the time of a series output: nothing selects them."""
    if isinstance(value, list):
        raise ValueError(
            "time = [dates] selects nothing: the output would be read at every step, as "
            "with 'all'. Bound what is scored with [metrics] window or window, or "
            "write 'first' or 'last'."
        )
    return value


OutputTime = Annotated[Literal["all", "last", "first"], BeforeValidator(_no_list_of_dates)]


class CalibWindow(HydroModelBase):
    """Dates bounding the samples a metric is computed on.

    A window in dates rather than in sample counts: it says the same thing
    whatever the output frequency.
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
    def _check_bounds(self) -> CalibWindow:
        bounds = _parsed_bounds(self)
        if bounds[0] is not None and bounds[1] is not None and bounds[0] > bounds[1]:
            raise ValueError(f"window start {self.start!r} is after end {self.end!r}.")
        return self


def _parsed_bounds(window: CalibWindow) -> tuple[Any, Any]:
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
            raise ValueError(f"window {label}={raw!r} is not a date.") from exc
    return parsed[0], parsed[1]


def window_bounds(window: CalibWindow | None) -> tuple[Any, Any] | None:
    """Return the parsed ``(start, end)`` of a window, or None when unset."""
    if window is None:
        return None
    return _parsed_bounds(window)


def _a_steady_span(window: dict[str, str]) -> dict[str, str]:
    """Read a steady span, a window that needs both of its bounds."""
    missing = [key for key in ("start", "end") if not window.get(key)]
    if missing:
        raise ValueError(
            f"steady_window needs both 'start' and 'end'; missing {', '.join(missing)}."
        )
    CalibWindow.model_validate(window)
    return dict(window)


ProtocolSteadySpan: TypeAlias = Annotated[
    dict[Literal["start", "end"], str], AfterValidator(_a_steady_span)
]
"""A ``{start, end}`` table of ISO dates, both bounds required."""


class MatchingHydrographicNetworkOptions(HydroModelBase):
    """What a file may say about the protocol beyond naming it.

    Every default here is the value of the publication or a departure the protocol
    declares and prints (``Deviation``). The names are the ones the file uses for
    its own parameters and outputs, and the engines are free: the method is the
    pair of criteria and the order they run in, not the optimizer that walks them.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        **_renamed(
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
        "observed_station_id": _GAUGE_ADVICE,
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
        AfterValidator(_validated_method_for("calibration.protocol.steady_method")),
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
        json_schema_extra={"value_docs": _METRIC_VALUE_DOCS},
    )
    transient_method: Annotated[
        str,
        Profile.USER,
        AfterValidator(_validated_method_for("calibration.protocol.transient_method")),
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
            _check_the_method_takes_its_options(
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


CalibrationProtocolDecl: TypeAlias = MatchingHydrographicNetworkOptions
"""What ``[calibration].protocol`` validates against.

One registered protocol today, so the alias names it directly. A second one
turns this into a union discriminated on ``name``; the registry and this alias
are kept in step by
``tests/unit/calibration/test_runners_phase_regime.py``.
"""


class CalibParameterDecl(HydroModelBase):
    """User declaration for one calibrated parameter.

    The declaration is read from ``[calibration.parameters.<name>]``, and the
    section name is the quantity: it is resolved against the catalog the
    project exposes, so a file states the range and nothing else. Writing
    ``path`` is the way out for whatever the catalog does not reach, and it
    wins without a lookup.

    Use ``mode="replace"`` for direct parameter values and ``mode="scale"``
    for multiplicative factors applied to an existing config value.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        **_renamed(
            {
                "transform": ("search_space", "the space the search walks the parameter in"),
                "prior": ("sampling", "the law that starting points and random draws follow"),
            }
        ),
    }

    bounds: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        min_length=2,
        max_length=2,
        description="[low, high] physical bounds, in 'units' when the file writes it, "
        "else in the unit the target declares. "
        "Falls back to what the field annotates when the file omits it, which most "
        "fields deliberately leave unset because a range belongs to the site.",
    )
    search_space: Annotated[Literal["identity", "log", "logit"], Profile.USER] = Field(
        default="identity",
        json_schema_extra=field_metadata(
            renamed_from=["calibration.parameters.transform"],
            value_docs={
                "identity": "Searches the value as written.",
                "log": (
                    "Searches the logarithm of the value: for a positive quantity that "
                    "spans orders of magnitude."
                ),
                "logit": (
                    "Searches log(x / (1 - x)): for a share strictly between 0 and 1. "
                    "Both bounds must lie inside (0, 1)."
                ),
            },
        ),
        description="Space the search walks the parameter in. 'log' for "
        "strictly-positive quantities spanning orders of magnitude. Unset, the "
        "target's own field decides: a hydraulic conductivity declares 'log' where "
        "it is defined, so a file states this only to depart from it.",
    )
    sampling: Annotated[Literal["uniform", "log_uniform", "normal"], Profile.USER] = Field(
        default="uniform",
        description=(
            "Distribution, between the bounds, that starting points, random draws and "
            "Bayesian samplers take values from."
        ),
        json_schema_extra=field_metadata(
            renamed_from=["calibration.parameters.prior"],
            value_docs={
                "uniform": "Every value between the bounds is equally likely.",
                "log_uniform": "Every decade between the bounds is equally likely.",
                "normal": (
                    "A normal law centred between the bounds, with a standard deviation "
                    "of a sixth of their span, cut at the bounds."
                ),
            },
        ),
    )
    path: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Dotted TOML path of the value to move, such as "
        "'flow.param.K.field.value'. Optional, and the way out "
        "rather than the way in: when omitted, the section name is resolved against "
        "the project catalogue ('hmp config targets' lists it). Write one to reach a "
        "value the catalogue does not carry, or to settle a name two targets answer "
        "to. A path written here wins without a lookup. When the catalogue carries it, "
        "the parameter inherits the field's space and draw like a named one; when it "
        "does not, nothing is inherited and the sample is written as it is drawn.",
    )
    target: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Readable alias for 'path'. Setting both is refused.",
    )
    mode: Annotated[ParameterMode, Profile.USER] = Field(
        default="replace",
        description="'replace' writes the sampled value as-is; 'scale' multiplies "
        "the base TOML value at the target path by the sample.",
    )
    units: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Unit the bounds are written in, such as 'm/s'. For a parameter the catalogue "
            "resolves, bounds in another unit of the same quantity are converted when the "
            "file loads into the unit the target is read in, and the search draws, writes "
            "and reports its samples in that unit ('hmp config targets' lists it). A unit "
            "of another quantity is refused. Unset, the unit of the target applies. With "
            "mode = 'scale' the bounds are factors without a unit, and writing one is "
            "refused. For a path outside the catalogue it is the unit the bounds are "
            "checked against the physical range in."
        ),
        examples=["m/s"],
    )

    @model_validator(mode="after")
    def _check_one_address(self) -> CalibParameterDecl:
        if self.path is not None and self.target is not None:
            raise ValueError(
                f"a parameter writes both path={self.path!r} and target={self.target!r}, "
                "two names for one address. Keep one of them."
            )
        return self

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
        json_schema_extra={"value_docs": _OUTPUT_REDUCER_VALUE_DOCS},
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
        import warnings

        warnings.warn(
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
        json_schema_extra={"value_docs": _OUTPUT_REDUCER_VALUE_DOCS},
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
        json_schema_extra={"value_docs": _OUTPUT_REDUCER_VALUE_DOCS},
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
        json_schema_extra={"value_docs": _OUTPUT_REDUCER_VALUE_DOCS},
    )
    observed_values: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        description="Hard-coded observed values, positional and dateless. Name a "
        "station in 'observes' to score a record the project loaded instead.",
    )


def _moved_from(*keys: str, **metadata: Any) -> dict[str, Any]:
    """Return the metadata of a network field that holds these old keys of its output."""
    return field_metadata(renamed_from=[f"calibration.outputs.{key}" for key in keys], **metadata)


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
        json_schema_extra=_moved_from("heads_snap_radius"),
    )
    min_drained_area: Annotated[float, Profile.USER] = Field(
        default=STREAM_CRITERION_DEFAULTS.heads_min_drained_area_km2,
        ge=0.0,
        description="The drained area a cell needs before a head may land on it, so a head "
        "next to its valley lands in the valley and not on the ridge cell beside it.",
        json_schema_extra=_moved_from("heads_min_drained_area_km2", unit="km2"),
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
        json_schema_extra=_moved_from("stream_geometry_path", "observed_network", site_scoped=True),
    )
    permanent: Annotated[Literal["data.hydrography"] | OptionalPath, Profile.USER] = Field(
        default=None,
        description="The permanent map, the reaches that flow all year, which the complete "
        "map contains: a vector file, read as it is and never filtered by attribute, or "
        "'data.hydrography', the permanent reaches the hydrography data family wrote beside "
        "its network. A source that does not say which reaches flow all year gives none. "
        "The complete map scored is the union of the two, and the share of this map outside "
        "the complete one is published.",
        json_schema_extra=_moved_from("minimal_stream_geometry_path", "minimal_observed_network"),
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
        json_schema_extra=_moved_from("extent.weights"),
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
        json_schema_extra=_moved_from("observed_rasterization"),
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
        json_schema_extra=_moved_from("clip_map_to_catchment"),
    )
    position_accuracy: Annotated[Length | None, Profile.USER] = Field(
        default=None,
        description="Positional accuracy of the map. It enters the automatic validity length "
        "only, so it is refused beside a 'verdict.validity_length' written as a length: the "
        "cell size h there is max(h_obs, this), because a map is not placed better when the "
        "mesh is refined. r_optim stays D_optim / h_obs, the paper's Eq. 3. Unset is the "
        "literal reading of the paper.",
        json_schema_extra=_moved_from("observed_position_accuracy"),
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
        **_renamed(
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
        json_schema_extra=_moved_from(
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
        json_schema_extra=_moved_from("extent.minimal_dry_steps", "extent.minimal_dry_duration"),
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
        json_schema_extra=_moved_from("tau_specific_ratio", unit="-"),
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
        json_schema_extra=_moved_from("diagonal_neighbors"),
    )
    weighting: Annotated[Literal["cell", "area"], Profile.USER] = Field(
        default="cell",
        description="Average one cell one vote (the paper) or weighted by cell area. "
        "Both values are always reported; use 'area' on a mesh refined along the "
        "streams, where cell density is highest exactly where distances are smallest.",
        json_schema_extra={
            **_moved_from("weighting"),
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
        json_schema_extra=_moved_from("extent"),
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
        json_schema_extra=_moved_from("validity_length"),
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
        json_schema_extra=_moved_from("on_roptim_violation"),
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
        json_schema_extra=_moved_from("alpha_warning_threshold"),
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
        json_schema_extra=_moved_from("clipping_warning_share", unit="-"),
    )
    clipping_warning_gap: Annotated[float, Profile.EXPERT] = Field(
        default=STREAM_CRITERION_DEFAULTS.clipping_warning_gap,
        ge=0.0,
        le=1.0,
        description="Minimum absolute gap between the whole-mesh and the catchment "
        "alpha for the clipping report to fire. A linework spilling out of the "
        "catchment over ground that routes the same way leaves the two ratios equal, "
        "and reporting it there would be noise on every ordinary project.",
        json_schema_extra=_moved_from("clipping_warning_gap"),
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
        **_renamed(
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


class CalibObjectiveBlockDecl(HydroModelBase):
    """Weighted metric block used by a composite objective.

    A block consumes one or more named outputs, applies one metric, and
    contributes ``weight`` to the final minimization cost. Blocks make mixed
    objectives explicit, for example combining heads, discharge, and transport
    signals in one calibration session.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        **_renamed(
            {
                "transform": (
                    "cost_transform",
                    "the function applied to the cost of this block",
                ),
            }
        ),
        "warmup": (
            "a window bounds every block: write window = {start = <date>} on [calibration] instead"
        ),
    }

    name: Annotated[str, Profile.USER] = Field(
        description="Unique block identifier used in logs and persistence.",
    )
    metric: Annotated[MetricKind, Profile.USER] = Field(
        description="Metric that scores this block against its observations.",
        json_schema_extra={"value_docs": _METRIC_VALUE_DOCS},
    )
    weight: Annotated[PositiveFloat, Profile.USER] = Field(
        default=1.0,
        description=(
            "Weight of this block in the sum of the block costs. Only the ratios between "
            "weights matter."
        ),
        json_schema_extra={"unit": "-"},
    )
    uses_outputs: Annotated[list[str], Profile.USER] = Field(
        min_length=1,
        description=(
            "Outputs (by name) consumed by this block. An error metric (rmse, mae) or a "
            "network distance may read several, pooled into one cost. A metric that rises "
            "with the fit (nse, kge and the other efficiencies) reads exactly one: write "
            "one block per output, each with its weight, so the costs average per station."
        ),
    )
    normalize_cost: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="When True, divide the block cost by a reference scale, so it adds "
        "to other blocks as a pure number and a share means a share. On a residual "
        "metric (rmse, mae) the scale is the standard deviation of the observations, "
        "their mean absolute value if that is zero. On a network distance "
        "(distance_gap, distance_mean) it is the output's validity_length, 2 h_obs "
        "under 'auto': a gap of one validity length costs 1, as much as an NSE of 0 on "
        "nse_log. Refused on an efficiency score, already a pure number.",
    )
    cost_transform: Annotated[ObjectiveTransform, Profile.USER] = Field(
        default="identity",
        description="Transform applied to the cost of this block before weighting. Note "
        "that cost_transform='log' takes the logarithm of the cost, which is not the same "
        "thing as metric='nse_log', an NSE computed on log-transformed series.",
        json_schema_extra=field_metadata(
            renamed_from=["calibration.objective_blocks.transform"],
            value_docs={
                "identity": "Uses the block cost as computed, with no transform.",
                "log": "Takes log10 of the cost plus a small epsilon, compressing "
                "large costs before weighting.",
                "inverse": "Takes -1 / (cost + epsilon), sharpening the gradient near "
                "a cost of zero.",
            },
        ),
    )

    @model_validator(mode="after")
    def _check_an_efficiency_reads_one_output(self) -> CalibObjectiveBlockDecl:
        """Refuse an efficiency over several outputs.

        The pool of several stations has the spread between them as variance, so
        one badly simulated station hides behind it. One block per output
        averages the costs per station instead.
        """
        metric = str(self.metric).lower()
        if METRIC_SENSE.get(metric) == "max" and len(self.uses_outputs) > 1:
            listed = ", ".join(repr(name) for name in self.uses_outputs)
            raise ValueError(
                f"block {self.name!r} scores {metric!r} on {len(self.uses_outputs)} outputs "
                f"({listed}). An efficiency computed on the pool of several outputs is not "
                "the mean of their efficiencies, and a poorly simulated station hides "
                "behind the spread between stations. Write one block per output, each "
                "with its weight, so the costs average per station."
            )
        return self

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
``tests/unit/calibration/test_runners_phase_regime.py`` keeps the two equal.
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


_OPTIONS_WITHOUT_A_METHOD = (
    "{where} gives method_options and no method. They are options of one method, "
    "and a search that names no method gets the one its criteria call for. Write "
    "method beside them or under [calibration], or drop them."
)


def _check_the_method_takes_its_options(
    where: str, method: str | None, options: Mapping[str, Any], *, key: str = "method_options"
) -> None:
    """Refuse options with no method, and options the method written does not take.

    Checked when the file loads, so a phase-two option its method does not know
    is refused before phase one spends its budget. A method this package has no
    model for, a plugin's, is left to its own constructor.
    """
    if not options:
        return
    if method is None:
        raise ValueError(_OPTIONS_WITHOUT_A_METHOD.format(where=where))
    from hydromodpy.calibration.optim.method_config import method_options_problem

    problem = method_options_problem(method, options)
    if problem is not None:
        raise ValueError(f"{where} {key}: {problem}")


UncertaintyMethod = Literal["cost_profile", "multistart", "linearized"]

_UNCERTAINTY_METHOD_VALUE_DOCS: dict[str, str] = {
    "cost_profile": (
        "Reads the range of sampled values whose cost stayed within cost_margin of the "
        "best, off the trace of the search. No extra model run."
    ),
    "multistart": (
        "Repeats the whole search restarts times from different starting points and "
        "reports the spread of the optima. It can see a second basin."
    ),
    "linearized": (
        "Linearizes the model about the optimum: one extra run per parameter gives a "
        "first-order covariance, and with it which parameters trade off."
    ),
}
"""What each way of computing a calibration interval does."""


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


_UNCERTAINTY_REFUSED_KEYS: Mapping[str, str] = {
    "tolerance": renamed_to(
        "tolerance", "cost_margin", "write '5%' or '25 m', a share of the best cost or a length"
    ),
    "mode": renamed_to(
        "mode", "cost_margin", "its unit says what mode said: '5%' is relative, '25 m' absolute"
    ),
}
"""The two keys that said how wide an interval is, now one margin that carries its unit."""


def _checked_cost_margin(value: Any) -> Any:
    """Return *value* when it reads as a share or a length, else raise ``ValueError``."""
    if value is None:
        return value
    parse_cost_margin(value)
    return value.strip()


def _margin_in_metres_needs_distances(where: str, text: str) -> str:
    return (
        f"{where} cost_margin = {text!r} is a length, and no search it covers is scored only "
        "by network distances (distance_gap, distance_mean): a length bounds a cost in "
        "metres. Write a share such as '5%', or leave it unwritten."
    )


class CalibPhaseUncertaintyDecl(HydroModelBase):
    """How wide one phase says its answer is, key by key over ``[calibration.uncertainty]``.

    Every key is optional and has the meaning it has in the section. A key
    written here wins for this phase. A key left out takes the section's value,
    then the default that follows what the phase scores. ``restarts`` and
    ``perturbation`` belong to a method: a phase that names another method than
    the section does not inherit them.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = _UNCERTAINTY_REFUSED_KEYS

    method: Annotated[UncertaintyMethod | None, Profile.USER] = Field(
        default=None,
        description="How this phase's interval is obtained: 'cost_profile', "
        "'multistart' or 'linearized', read as in [calibration.uncertainty] method.",
        json_schema_extra={"value_docs": _UNCERTAINTY_METHOD_VALUE_DOCS},
    )
    restarts: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=2,
        description="How many times method='multistart' repeats this phase's search.",
        json_schema_extra={"unit": "-"},
    )
    perturbation: Annotated[PositiveFloat | None, Profile.USER] = Field(
        default=None,
        description="Relative step of method='linearized' for this phase, as a fraction "
        "of each calibrated value.",
        json_schema_extra={"unit": "-"},
    )
    cost_margin: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Width of this phase's interval, with its unit: '5%' is a share of "
        "the best cost, '75 m' a length, for a phase scored only by network distances. "
        "Unset here and in [calibration.uncertainty], one mesh cell for a phase scored "
        "only by network distances, five per cent of the best cost otherwise.",
        json_schema_extra=field_metadata(
            unit="% or m",
            renamed_from=[
                "calibration.phases.uncertainty.tolerance",
                "calibration.phases.uncertainty.mode",
            ],
        ),
    )

    @field_validator("cost_margin", mode="before")
    @classmethod
    def _read_the_margin(cls, value: Any) -> Any:
        """Refuse a margin without its unit, or that is neither a share nor a length."""
        return _checked_cost_margin(value)

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
    method accepts a start point. It reads "pass on if the search settled",
    never "pass on if the result is good": the engine met its own rule or
    solved every point of its plan, or an engine with no rule of its own (a
    random search) spent its budget, which the phase then says. A validity
    indicator qualifies a result, and a phase that returns a coarse agreement
    still returns a number.
    The state of that indicator travels to the later phases and into the
    report, so a value calibrated on top of a doubtful one carries the mention
    all the way out.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        **_renamed(
            {
                "scoring_window": ("window", "the dates this phase scores"),
                "optimizer_kwargs": ("method_options", "options of this phase's method"),
                "max_iter": ("max_trials", "evaluations this phase may run"),
                "tolerance": ("precision", "how finely this phase pins its parameters"),
            }
        ),
        "observed_station_id": _GAUGE_ADVICE,
    }

    name: Annotated[NonEmptyStr, Profile.USER] = Field(
        description="Phase identifier, unique in the calibration and used in the "
        "session directory and in the report.",
    )
    description: Annotated[str, Profile.USER] = Field(
        default="",
        description="What this phase calibrates and against what, in one sentence.",
    )
    method: Annotated[
        Annotated[str, AfterValidator(_validated_method_for("calibration.phases.method"))] | None,
        Profile.USER,
    ] = Field(
        default=None,
        description=(
            "Optimization method for this phase only. Unset, the phase runs the "
            "method [calibration] writes; failing that it follows from what the "
            "phase scores: 'bisection' when the phase moves one parameter in log space "
            "and every one of its blocks is signed (distance_gap), since the answer is "
            "then a zero to find; 'scipy_nelder_mead' otherwise, a cost to minimise. "
            "hmp calibrate --list-phases prints the method and where it comes from. "
            "Write it to depart from that choice, and whenever method_options are given "
            "and [calibration] writes no method. "
            "Built-ins: 'grid' (regular sweep, sized by "
            "method_options.points_per_dim), 'lhs' (stratified Latin hypercube, "
            "sized by method_options.n_samples), 'random_search', 'bisection' (root of "
            "a signed criterion on one parameter, the stream-network stage), 'optuna' "
            "(TPE), 'cma_es', 'scipy_de', 'scipy_nelder_mead' and 'gp_mapping'. "
            "An unknown name is refused when the file is read, "
            "with the list installed here."
        ),
    )
    max_trials: Annotated[PositiveInt | Literal["auto"] | None, Profile.USER] = Field(
        default=None,
        description="Maximum number of evaluations for this phase. Unset, the phase "
        "takes the max_trials of [calibration]. 'auto' lets an "
        "engine that counts its evaluations size it: the bisection budgets its worst "
        "case, the grid and the Latin hypercube their design, and each refuses before "
        "the first solve a number below its nominal count "
        "(see [calibration].max_trials). Any other engine gets 100 from 'auto', and no "
        "extension when it spends them before its stopping rule.",
        json_schema_extra=field_metadata(renamed_from=["calibration.phases.max_iter"], unit="-"),
    )
    precision: Annotated[PositiveFloat | None, Profile.USER] = Field(
        default=None,
        description=(
            "How precisely the search has to pin a parameter before it stops, as a "
            "relative precision on the parameter itself: 0.01 asks for one per cent, "
            "0.1 for ten. On a parameter searched in log space that is a ratio, which is "
            "how a conductivity is known in the first place, and it holds wherever the "
            "value sits; on any other search space there is no scale on the value to be "
            "relative to before the search has one, so it reads as a fraction of the "
            "declared interval. Each engine's own stopping option is written from it, "
            "so the same number survives a change of engine, and the engine's own "
            "option stays available for reproducing a published call verbatim. Unset, "
            "the phase takes the precision of [calibration] when its engine stops on "
            "one and the phase writes no stopping option of its own, else the engine's "
            "default applies. Written here, an engine that stops on its budget rather "
            "than on a precision refuses it rather than ignore it."
        ),
        json_schema_extra=field_metadata(unit="-", renamed_from=["calibration.phases.tolerance"]),
    )
    batch_size: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description="Suggestions drawn per ask, at least ``parallel``. Unset, the "
        "phase takes the ``batch_size`` of ``[calibration]``.",
        json_schema_extra={"unit": "-"},
    )
    parallel: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description="Trials of this phase solved side by side, each in its own folder. "
        "Unset, the phase takes the ``parallel`` of ``[calibration]``, which also "
        "reaches the phases a protocol writes.",
        json_schema_extra={"unit": "-"},
    )
    parameters: Annotated[list[str], Profile.USER] = Field(
        min_length=1,
        description="Names of the calibration parameters this phase may move. Every "
        "other parameter keeps the value it entered the phase with.",
    )
    bounds: Annotated[dict[str, list[float]] | None, Profile.USER] = Field(
        default=None,
        description="[low, high] physical bounds this phase searches a parameter between, "
        "as {parameter = [low, high]}, in the unit the parameter declares. Only parameters "
        "the phase moves, and every interval has to lie inside the bounds of "
        "[calibration.parameters.<name>] (or the range the field annotates when the "
        "section writes none): a phase narrows a search, it never widens it. A parameter "
        "left out keeps the bounds of the section. hmp calibrate --list-phases prints them.",
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
        description=(
            "Name of the simulated variable, or of a [calibration.outputs] entry, that "
            "objective scores when this phase uses no objective block. Unset, the "
            "variable of [calibration] applies."
        ),
    )
    objective: Annotated[MetricKind | None, Profile.USER] = Field(
        default=None,
        description="Metric scoring this phase's single simulated series, when the "
        "phase does not use objective blocks. Same vocabulary as a block's 'metric'.",
        json_schema_extra={"value_docs": _METRIC_VALUE_DOCS},
    )
    method_options: Annotated[dict[str, Any] | None, Profile.USER] = Field(
        default=None,
        description="Options of this phase's method, named as that method names "
        "them: sweep_points for 'bisection', points_per_dim for 'grid', sampler for "
        "'optuna'. They belong to one method, so a phase that gives them writes "
        "method beside them, or runs the method [calibration] writes. Unset, the phase "
        "takes the method_options of [calibration] when it runs the method that section "
        "writes, and none otherwise; an empty table states that it takes none. A key "
        "the method does not take is refused when the file loads. hmp config check "
        "names the phase.",
        json_schema_extra=field_metadata(renamed_from=["calibration.phases.optimizer_kwargs"]),
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
    steady_window: Annotated[
        dict[str, str] | None, Profile.USER, VisibleWhen("regime", "steady")
    ] = Field(
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
    window: Annotated[CalibWindow | None, Profile.USER] = Field(
        default=None,
        description="Dates bounding the samples this phase scores on, replacing "
        "[calibration].window. start = the first date scored leaves a spin-up "
        "out of every block alike. A network output read in one state is dated at the "
        "stamp of that state, which has to lie inside the window.",
        json_schema_extra=field_metadata(renamed_from=["calibration.phases.scoring_window"]),
    )
    depends_on: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Name of the phase that must run first. The values it passes on "
        "enter this one fixed, except those this phase lists and moves again. When that "
        "phase freezes its values and its search stops on its budget before a rule of its "
        "own, this phase is refused rather than run on the values of the file.",
    )
    freeze_on_success: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Pass the values this phase found to the phases after it. A later "
        "phase holds them fixed, unless it lists the parameter: it then moves it again, "
        "starting from the passed value when its method accepts a start point. When two "
        "phases pass on the same parameter, the later one wins. Success means the search "
        "met its own rule or solved every point of its plan, not that its validity "
        "indicator is good. A search with no rule of its own (random_search, cma_es) that "
        "spends its budget also passes on its best trial, and the phase says it froze the "
        "best of a budget-only search. One with a rule that its budget stops first passes "
        "nothing on.",
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

    @field_validator("bounds")
    @classmethod
    def _each_interval_is_two_ordered_values(
        cls, value: dict[str, list[float]] | None
    ) -> dict[str, list[float]] | None:
        """Refuse an interval that is not [low, high] with low below high."""
        for name, interval in (value or {}).items():
            if len(interval) != 2:
                raise ValueError(
                    f"bounds of {name!r} has to be [low, high], two values, got {interval!r}."
                )
            if not interval[0] < interval[1]:
                raise ValueError(
                    f"bounds of {name!r} = {interval!r}: the lower bound must be below the upper."
                )
        return value

    @model_validator(mode="after")
    def _name_the_engine_the_options_belong_to(self) -> CalibPhaseDecl:
        """Refuse method_options its own method does not take, when the file loads.

        A phase that names no method runs the one ``[calibration]`` writes, or
        failing that the one its criteria call for, and
        :meth:`CalibrationConfig._check_phases` reads the options against it.
        """
        if self.method is not None:
            _check_the_method_takes_its_options(
                f"phase {self.name!r}", self.method, self.method_options or {}
            )
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

    ``weighting``, ``nested_gauges`` and ``on_member_failure`` were declared
    here and never read: a file that wrote them got the same cost. They are
    refused as keys of a pre-release of 2.0.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        **_never_read("weighting", "nested_gauges", "on_member_failure"),
    }

    min_samples: Annotated[int, Profile.USER] = Field(
        default=1,
        ge=1,
        description=(
            "Fewest paired samples a member may be scored on. An alignment that "
            "collapses to three days still returns a number, and a weight of 65 per "
            "cent resting on three days is not what the file says it is."
        ),
        json_schema_extra={"unit": "-"},
    )


class CalibUncertaintyDecl(HydroModelBase):
    """How wide the search says its own answer is.

    The calibrated value never moves: this block only decides what is reported
    beside it. ``cost_profile`` reads the interval off the trials the search
    already ran, so it costs no extra model run and rests on no error model. It
    says what the search could not tell apart, which is a statement about the
    trace and not a posterior.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = _UNCERTAINTY_REFUSED_KEYS

    method: Annotated[UncertaintyMethod, Profile.USER] = Field(
        default="cost_profile",
        json_schema_extra={"value_docs": _UNCERTAINTY_METHOD_VALUE_DOCS},
        description=(
            "How the interval around each calibrated value is obtained. "
            "'cost_profile' reads the range of sampled values whose cost stayed within "
            "'cost_margin' of the best, off the trace the search already produced, and "
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
        json_schema_extra={"unit": "-"},
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
        json_schema_extra={"unit": "-"},
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

    cost_margin: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Width of the interval, written with its unit. '5%' is a share of the best "
            "cost, the usual choice for an efficiency score. A criterion solved at zero, "
            "such as the stream-network gap, has no fraction of itself to take: write a "
            "length, '25 m', which is only read by a search scored only by network "
            "distances (distance_gap, distance_mean). A bare number is refused. Unset, it "
            "follows what the search scores: one mesh cell, in metres, for a search scored "
            "only by network distances, because a stream cannot move by less than a cell; "
            "5%, five per cent of the best cost, otherwise. The cell is the median distance "
            "between the centres of neighbouring cells, measured by the network criterion "
            "on the mesh it scores. A phase may write its own, which wins. hmp config "
            "check refuses a share on a search scored only by network distances."
        ),
        json_schema_extra=field_metadata(
            unit="% or m",
            renamed_from=["calibration.uncertainty.tolerance", "calibration.uncertainty.mode"],
        ),
    )

    @field_validator("cost_margin", mode="before")
    @classmethod
    def _read_the_margin(cls, value: Any) -> Any:
        """Refuse a margin without its unit, or that is neither a share nor a length."""
        return _checked_cost_margin(value)


def _registered_evaluator(value: str | None) -> str | None:
    """Refuse an evaluator this installation cannot serve, while reading the document.

    Here rather than at the first trial because a file naming an evaluator nobody
    installed is a broken document, and learning that after ``prepare_trials`` has
    run the whole geographic, mesh and data prefix costs that prefix.

    ``None`` is not checked: it means "whatever this build defaults to", and a
    default that does not resolve is an environment fault the registry reports
    with its own message.
    """
    if value is None:
        return value
    from hydromodpy.calibration.evaluation import registry as evaluator_registry

    return check_registered_name(
        value,
        evaluator_registry.evaluators.names(),
        key="calibration.evaluator",
        group=evaluator_registry.ENTRY_POINT_GROUP,
    )


class CalibrationConfig(HydroModelBase):
    """Top-level ``[calibration]`` section.

    The config selects the optimizer, iteration budget, candidate persistence
    policy, parameter declarations, observable outputs, and objective blocks.
    It is the user-facing schema used by CLI calibration and
    ``Project.calibrate``. This section and the shape of ``CalibrationReport``
    are experimental until the rework of the calibration is published.

    When no explicit objective block is declared, HydroModPy can synthesize one
    from ``objective`` and ``variable`` if the matching output exists.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        **_renamed(
            {
                "scoring_window": ("window", "the dates every metric is scored on"),
                "optimizer_kwargs": ("method_options", "options of the method"),
                "max_iter": ("max_trials", "the evaluations the search may run"),
                "tolerance": ("precision", "how finely the search pins a parameter"),
            }
        ),
        "observed_station_id": _GAUGE_ADVICE,
        "warmup_periods": (
            "write window = {start = <date>} instead, with [simulation.time] "
            "start_datetime plus that many steps as the date. "
            + prerelease_refusal(_THIS_TABLE, ["warmup_periods"])
        ),
        # Declared and never read. The promoted run follows
        # [simulation.results.persistence], never these.
        **_never_read("lightweight_extraction", "persist_model_distribution", "persistence"),
        "rerun_best_with_outputs": (
            "the best trial is promoted by default: save_runs = 'best_n' with "
            "save_best_n = 1 writes it under runs/<case>/."
        ),
        "candidates_root": (
            "materialize_candidates writes under sessions/<case>/candidates/; there is "
            "no other place."
        ),
        "reuse_completed_phases": (
            "hmp calibrate --resume reuses the completed phases of the session of the "
            "case; nothing in the file says so."
        ),
    }

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
            "that choice, and whenever method_options are given. A phase of "
            "[[calibration.phases]] names its own. "
            "Built-ins: 'grid' (regular sweep, sized by "
            "method_options.points_per_dim), 'lhs' (stratified Latin hypercube, "
            "sized by method_options.n_samples), 'random_search', 'bisection' (root of "
            "a signed criterion on one parameter, the stream-network stage), 'optuna' "
            "(TPE), 'cma_es', 'scipy_de', 'scipy_nelder_mead' and 'gp_mapping'. "
            "An unknown name is refused when the file is read, "
            "with the list installed here. "
            "Optuna is installed by default; install the calibration extra for "
            "cma_es and Optuna's cmaes sampler."
        ),
    )
    evaluator: Annotated[str | None, Profile.USER, AfterValidator(_registered_evaluator)] = Field(
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
    max_trials: Annotated[PositiveInt | Literal["auto"], Profile.USER] = Field(
        default="auto",
        json_schema_extra=field_metadata(renamed_from=["calibration.max_iter"], unit="-"),
        description=(
            "Maximum number of evaluations of the search. It is the only bound on how "
            "long a search runs: no method option counts evaluations of its own. 'auto' lets an engine that "
            "counts its evaluations before the first solve size its own budget. Three "
            "do. The grid and the Latin hypercube count their design, one evaluation "
            "per point, and refuse a smaller number before the first solve, since a "
            "sweep cut short is not its design. The bisection counts with d the "
            "declared interval in decades, t = "
            "log10(1 + rel_tol), S the sweep points (counted as 2 for sweep_points 0), s = d / "
            "(S - 1) and E = bracket_expand, a root inside the bounds costs S + "
            "ceil(log2(s / t)) and one found after e expansions S + 2e + "
            "ceil(log2(1 / t)); 'auto' budgets the largest, 23 on [1e-7, 1e-3] m/s "
            "with seven points and one per cent (15 inside the bounds). A number "
            "below the nominal count is refused before the first solve, one below the "
            "worst case is announced, and a budget that still runs out gets exactly "
            "the halvings left, once. Any other engine gets 100 from 'auto' and no "
            "extension: a search that spends its budget before its own stopping rule "
            "is reported as not converged, and a re-run with a larger max_trials "
            "replays the trials already solved from the cache."
        ),
    )
    precision: Annotated[PositiveFloat | None, Profile.USER] = Field(
        default=None,
        description=(
            "How precisely the search has to pin a parameter before it stops, as a "
            "relative precision on the parameter itself: 0.01 asks for one per cent, "
            "0.1 for ten. On a parameter searched in log space that is a ratio, which is "
            "how a conductivity is known in the first place, and it holds wherever the "
            "value sits; on any other search space there is no scale on the value to be "
            "relative to before the search has one, so it reads as a fraction of the "
            "declared interval. Each engine's own stopping option is written from it, "
            "so the same number survives a change of engine, and the engine's own "
            "option stays available for reproducing a published call verbatim. Unset, "
            "the engine's default applies. An engine that stops on its budget rather "
            "than on a precision refuses this rather than ignore it."
        ),
        json_schema_extra=field_metadata(unit="-", renamed_from=["calibration.tolerance"]),
    )
    batch_size: Annotated[int, Profile.USER] = Field(
        default=1,
        ge=1,
        description="Number of suggestions drawn per ask, at least ``parallel``.",
        json_schema_extra={"unit": "-"},
    )
    parallel: Annotated[int, Profile.USER] = Field(
        default=1,
        ge=1,
        description=(
            "Trials solved side by side, each in its own folder, for every phase that "
            "sets none of its own. A grid or a random search evaluates its points "
            "together; a root search cuts its bracket into parallel + 1 parts; a "
            "simplex evaluates the candidates of one step together and keeps the "
            "sequential answer, so a width above 4 buys it nothing, and CMA-ES and "
            "differential evolution stop at their population. A width above 1 gives each worker process its own copy of "
            "the model (about 0.5 GiB, 3 s to start); 1 solves the trials one after the "
            "other in this process."
        ),
        json_schema_extra={"unit": "-"},
    )
    reject_water_budget_above: Annotated[float | None, Profile.USER] = Field(
        default=1.0,
        ge=0.0,
        description=(
            "Percent water-balance discrepancy of the whole model past which a trial is "
            "rejected instead of scored. The figure is the one the solver prints for the "
            "volume budget of the entire model, not the budget of a single package such "
            "as the lake package, which divides by small flows and reads higher. A "
            "rejected trial is marked failed, so it is neither ranked nor promoted: part "
            "of the water it routed came from nowhere and its cost is not comparable to "
            "a run that closed. Default 1.0 (one per cent). Raise it for a transient "
            "model whose lake or routed network legitimately sits higher. A TOML file "
            "has no null: to switch the gate off write a value no run reaches, such as "
            "1000, or pass None from Python. The worst time step of the run decides, "
            "not the last."
        ),
        json_schema_extra={"unit": "%"},
    )
    window: Annotated[CalibWindow | None, Profile.USER] = Field(
        default=None,
        description=(
            "Dates bounding the samples every metric is computed on: the way to leave a "
            "spin-up out, with start = the first date scored. A series keeps its stamps "
            "inside the window; a network output read in one state is dated at the stamp "
            "of that state, which has to lie inside it. A phase's own window replaces "
            "this one."
        ),
        json_schema_extra=field_metadata(renamed_from=["calibration.scoring_window"]),
    )
    validation_window: Annotated[CalibWindow | None, Profile.USER] = Field(
        default=None,
        description="Dates kept apart from the search, with both bounds. Every trial is scored "
        "on them beside its cost, by the blocks that compare a dated record, and the cost never "
        "reads them. [metrics] window minus these dates is the default of window. Declared once "
        "for the session, and a steady phase is not scored on it.",
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
    seed: Annotated[int | None, Profile.USER] = Field(
        default=None,
        description=(
            "Seed of the random draws of the search (starting points, samples). The "
            "same seed with the same file gives the same trials."
        ),
        json_schema_extra={"unit": "-"},
    )
    save_runs: Annotated[SaveRunsMode, Profile.USER] = Field(
        default="best_n",
        description=(
            "Which trials become runs once the search ends. Every trial leaves one "
            "line in sessions/<case>/trials.jsonl whatever the mode. 'best_n' promotes "
            "the best trial of the last phase to runs/<case>/, the calibrated run, and "
            "keeps the save_best_n - 1 next ones under sessions/<case>/trials/<n>/. "
            "'all' keeps every completed trial there. 'none' promotes nothing."
        ),
    )
    save_best_n: Annotated[int, Profile.USER] = Field(
        default=1,
        ge=0,
        description=(
            "Number of trials the 'best_n' mode of save_runs keeps as runs: 1 is the "
            "calibrated run alone, under runs/<case>/."
        ),
        json_schema_extra={"unit": "-"},
    )
    promote_phases: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Also promote the best trial of each phase before the last one, under "
            "sessions/<case>/phases/<phase>/best/. The calibrated run of the case is the "
            "best trial of the last phase whatever this says."
        ),
    )
    use_cache: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Enable params_hash content-addressable cache.",
    )
    objective: Annotated[MetricKind, Profile.USER] = Field(
        default="nse",
        description="Metric scoring the single simulated series, when no objective "
        "block is declared. Same vocabulary as a block's 'metric'; typed here so a "
        "bad value is reported against the key that was written.",
        json_schema_extra={"value_docs": _METRIC_VALUE_DOCS},
    )
    variable: Annotated[str, Profile.USER] = Field(
        default="head",
        description=(
            "Name of the simulated variable, or of a [calibration.outputs] entry, that "
            "objective scores when no objective block is declared."
        ),
    )
    method_options: Annotated[dict[str, Any], Profile.USER] = Field(
        default_factory=dict,
        description="Options of the method, named as that method names them: "
        "points_per_dim for 'grid', sampler for 'optuna', sweep_points for "
        "'bisection'. They belong to one method, so a calibration that gives them "
        "writes method beside them. A key the method does not take is refused when "
        "the file loads.",
        json_schema_extra=field_metadata(renamed_from=["calibration.optimizer_kwargs"]),
    )
    parameters: Annotated[dict[str, CalibParameterDecl], Profile.USER] = Field(
        default_factory=dict,
        description="Per-parameter declarations (bounds, search_space, sampling, path).",
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
    persist_iteration_detail: Annotated[PersistIterationDetail, Profile.USER] = Field(
        default="summary",
        description="How much of each trial's cost the session keeps: 'none' skips "
        "component metrics; 'summary' keeps block totals; "
        "'full' also stores per-block raw and normalized costs.",
    )
    persist_trial_series: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Write the simulated and observed series of every point/series "
        "output a completed trial scored (discharge at a gauge, head at a well...), "
        "as a small Parquet table per trial under the session folder. On by default "
        "under edition 2.1 (about 2 kB per trial on the island case), off under "
        "edition 2.0, the edition of a document that writes none. Network "
        "and spatial outputs carry no series and are never written here.",
    )
    materialize_candidates: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description=(
            "Write a standalone overlay TOML for each candidate under "
            "sessions/<case>/candidates/, so a trial can be replayed by hand."
        ),
    )
    aggregate: Annotated[CalibAggregateDecl, Profile.USER] = Field(
        default_factory=CalibAggregateDecl,
        description="How several scored targets become one cost: the fewest paired "
        "samples a member may be scored on.",
    )
    uncertainty: Annotated[CalibUncertaintyDecl, Profile.USER] = Field(
        default_factory=CalibUncertaintyDecl,
        description="How wide the search reports its own answer to be. The calibrated "
        "value is unaffected; this only decides the interval printed beside it. It is "
        "the default of every phase, and a phase may write its own keys.",
    )

    @model_validator(mode="after")
    def _check_the_costs_can_be_added(self) -> CalibrationConfig:
        """Refuse a weighted sum whose members are not in the same unit.

        ``normalize_cost`` exists for exactly this: it divides a block's cost by a
        reference scale so two blocks become comparable. Nothing enforced it, so a
        file could weight a head RMSE in meters at 0.5 and a discharge RMSE in
        m3/s at 0.5, believe it had split the cost evenly, and hand the meters
        whatever share their own magnitude happened to buy.

        The criterion declares whether its cost carries a unit; the outputs a
        block reads say which unit that is. A network distance is its own
        family, a length between two networks, whatever variable the release
        field is read from. A member is addable when it is dimensionless or
        normalized, and a sum of two that are neither, in different families,
        is refused. A network distance normalizes by the output's validity
        length, a residual by the spread of its observations.
        """
        from hydromodpy.calibration.criteria import criterion_for

        # Each phase adds the blocks it scores, so one is judged with those.
        for blocks in [self._blocks_scored_by(phase) for phase in self.phases or [None]]:
            if len(blocks) < 2:
                continue
            raw: dict[str, tuple[str, ...]] = {}
            residuals: set[str] = set()
            for block in blocks:
                if block.normalize_cost:
                    continue
                needs = criterion_for(str(block.metric)).requirements()
                if needs.cost_is_dimensionless:
                    continue
                if not needs.needs_observations and "network" in needs.reads_supports:
                    raw[str(block.name)] = (f"network distance in {needs.cost_unit or 'm'}",)
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
                residuals.add(str(block.name))
            distinct = {families for families in raw.values() if families}
            # A network distance is meant to sit beside pure numbers, a residual is not.
            beside_pure_numbers = bool(residuals) and len(raw) < len(blocks)
            if len(distinct) > 1 or beside_pure_numbers:
                listed = "; ".join(
                    f"{name!r} on {', '.join(families)}" for name, families in sorted(raw.items())
                )
                raise ValueError(
                    f"these blocks add a cost that carries a unit to a cost of another unit or "
                    f"to pure numbers: {listed}. The sum "
                    "would let the unit set the weighting instead of 'weight'. Declare "
                    "normalize_cost = true on each of them (a network distance is then "
                    "counted in validity lengths, a residual in the spread of its "
                    "observations), or score them on a metric whose cost is already a pure "
                    "number."
                )
        return self

    @model_validator(mode="after")
    def _name_the_engine_the_options_belong_to(self) -> CalibrationConfig:
        """Refuse method_options on a section that names no method, or that its method refuses.

        Same reason as on a phase: the options belong to one method, and the one a
        section gets when it names none follows from its criteria.
        """
        _check_the_method_takes_its_options("[calibration]", self.method, self.method_options)
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
        when ``method_options`` carries keys foreign to ``method`` so the
        failure happens at config-load time instead of inside the adapter
        constructor. A method left unwritten is checked as :meth:`method_for`
        chooses it.
        """
        from hydromodpy.calibration.optim.method_config import validate_method_kwargs

        method, _reason = self.method_for()
        validate_method_kwargs(method, self.method_options)

    def map_files(self) -> list[tuple[str, str, Path]]:
        """Return ``(output, map, path)`` for every map of a network output named by a file.

        The one list that anchors the paths on their document, hashes the files,
        freezes them in a session and checks that they are there.
        """
        return [
            (name, role, path)
            for name, output in self.outputs.items()
            if output.support == "network"
            for role, path in output.map.files().items()
        ]

    def phase_bounds_problems(self, phase: CalibPhaseDecl) -> list[str]:
        """Return why the bounds a phase writes cannot hold, or nothing.

        A phase moves the parameters it lists, between bounds that lie inside the
        section's. A parameter whose section bounds are not known yet (a field's
        range, filled in once the project is resolved) is not faced here; it is
        faced again when the phase is built.
        """
        problems: list[str] = []
        for name, interval in (phase.bounds or {}).items():
            if name not in phase.parameters:
                problems.append(
                    f"phase {phase.name!r} writes bounds for {name!r}, which it does not "
                    f"move; it moves {list(phase.parameters)}."
                )
                continue
            declared = self.parameters[name].bounds if name in self.parameters else None
            if declared is not None and not (
                declared[0] <= interval[0] and interval[1] <= declared[1]
            ):
                problems.append(
                    f"phase {phase.name!r} searches {name!r} between {interval}, which is "
                    f"not inside the bounds of [calibration.parameters.{name}], {declared}: "
                    "a phase narrows a search, it never widens it."
                )
        return problems

    def method_for(self, phase: CalibPhaseDecl | None = None) -> tuple[str, str | None]:
        """Return the method this calibration, or one of its phases, runs, and why.

        A method the file writes comes back as written, with no reason: the
        phase's own, else the section's. One it leaves unwritten is chosen from
        what the search scores, by ``optim.optimizer.choose_method``, and the
        reason says why. ``phase`` reads the parameters that phase moves and the
        blocks it scores, selected as the staged runner selects them; ``None``
        reads the whole section.
        """
        written = self.method if phase is None or phase.method is None else phase.method
        if written is not None:
            return written, None
        from hydromodpy.calibration.optim.optimizer import choose_method

        moved = self.parameters if phase is None else phase.parameters
        search_spaces = {
            name: str(self.parameters[name].search_space)
            for name in moved
            if name in self.parameters
        }
        choice = choose_method(search_spaces, self._criteria_scored_by(phase))
        return choice.method, choice.reason

    def max_trials_for(self, phase: CalibPhaseDecl | None = None) -> int | str:
        """Return the budget a search runs with: the phase's, else the section's."""
        own = None if phase is None else phase.max_trials
        return self.max_trials if own is None else own

    def precision_for(self, phase: CalibPhaseDecl | None = None) -> float | None:
        """Return the precision a search pins its parameters to: the phase's, else the section's.

        A precision written in the phase is returned as written, and
        ``hmp config check`` refuses it on an engine that stops on its budget. The
        section's reaches a phase only when the phase's engine stops on a
        precision, and not when the phase already writes that stopping option
        itself: the phase's own option departs from it, deliberately.
        """
        if phase is None:
            return self.precision
        if phase.precision is not None:
            return phase.precision
        if self.precision is None:
            return None
        from hydromodpy.calibration.optim.optimizer import engine_traits

        option = engine_traits(self.method_for(phase)[0]).precision_option
        if option is None or option in self.method_options_for(phase):
            return None
        return self.precision

    def method_options_for(self, phase: CalibPhaseDecl | None = None) -> dict[str, Any]:
        """Return the options a search's method runs with: the phase's, else the section's.

        An empty table in the phase states that it takes none. The section's
        reach a phase that names no options when that phase runs the method the
        section writes, since options belong to one method. A protocol writes
        its stages in full, so the options beside it reach none of them.
        """
        if phase is None:
            return dict(self.method_options)
        if phase.method_options is not None:
            return dict(phase.method_options)
        if self.protocol is not None or self.method is None:
            return {}
        if self.method_for(phase)[0] != self.method:
            return {}
        return dict(self.method_options)

    def search_sources_for(self, phase: CalibPhaseDecl) -> dict[str, str]:
        """Say where each key of a phase's search comes from: ``phase``, ``section`` or ``default``."""
        return {
            "method": (
                "phase"
                if phase.method is not None
                else "section"
                if self.method is not None
                else "default"
            ),
            "max_trials": (
                "phase"
                if phase.max_trials is not None
                else "section"
                if "max_trials" in self.model_fields_set
                else "default"
            ),
            "precision": (
                "phase"
                if phase.precision is not None
                else "section"
                if self.precision_for(phase) is not None
                else "default"
            ),
            "method_options": (
                "phase"
                if phase.method_options is not None
                else "section"
                if self.method_options_for(phase)
                else "default"
            ),
        }

    def uncertainty_for(self, phase: CalibPhaseDecl | None = None) -> CalibUncertaintyDecl:
        """Return the uncertainty a search reads: the phase's keys over the section's.

        ``None`` reads the section alone. A phase that names another method than
        the section does not inherit the section's ``restarts`` or
        ``perturbation``, which belong to the section's method. Nor does a phase
        scored by anything but network distances inherit a margin in meters.
        """
        own = None if phase is None else phase.uncertainty
        merged = self.uncertainty.model_dump()
        written = {} if own is None else own.model_dump(exclude_none=True)
        if written.get("method", self.uncertainty.method) != self.uncertainty.method:
            merged["restarts"] = None
            merged["perturbation"] = None
        if (
            phase is not None
            and "cost_margin" not in written
            and merged["cost_margin"] is not None
            and parse_cost_margin(merged["cost_margin"]).kind == "absolute"
            and not self._scored_on_network_distances(phase)
        ):
            merged["cost_margin"] = None
        merged.update(written)
        if merged == self.uncertainty.model_dump():
            return self.uncertainty
        return CalibUncertaintyDecl.model_validate(merged)

    def parallel_for(self, phase: CalibPhaseDecl | None = None) -> int:
        """Return how many trials a search solves side by side: the phase's, else the section's."""
        own = None if phase is None else phase.parallel
        return int(self.parallel if own is None else own)

    def batch_size_for(self, phase: CalibPhaseDecl | None = None) -> int:
        """Return how many suggestions a search draws per ask: the phase's, else the section's."""
        own = None if phase is None else phase.batch_size
        return int(self.batch_size if own is None else own)

    def interval_width_for(self, phase: CalibPhaseDecl | None = None) -> Any:
        """Return the width a search reads its interval with, and where it comes from.

        A ``cost_margin`` written in the phase wins, then the one written in
        ``[calibration.uncertainty]``. Left unwritten, it follows what the search
        scores, by ``optim.cost_margin.choose_interval_width``. ``phase`` reads the
        blocks that phase scores; ``None`` reads the whole section.

        The answer is an ``optim.cost_margin.IntervalWidth``. The signature does
        not name it because this module imports ``optim`` only inside a function.
        """
        from hydromodpy.calibration.optim.cost_margin import choose_interval_width

        own = None if phase is None or phase.uncertainty is None else phase.uncertainty.cost_margin
        text = self.uncertainty_for(phase).cost_margin
        written = None
        if text is not None:
            written = (parse_cost_margin(text), "phase" if own is not None else "section")
        return choose_interval_width(self._scored_on_network_distances(phase), margin=written)

    def objective_blocks_for(
        self, phase: CalibPhaseDecl | None = None
    ) -> list[tuple[CalibObjectiveBlockDecl, float]]:
        """Return the blocks a phase, or the whole section, scores, each with its weight.

        Selection is :meth:`_blocks_scored_by`, the same a search itself reads.
        The weight is the phase's own share when it names a table ``{block:
        share}``, else the block's declared weight -- unnormalized, the same
        way :class:`optim.objective.CompositeObjective` takes its own weights
        before dividing by their sum. Empty for a single-metric route
        (:attr:`CalibPhaseDecl.is_single_metric`, or the section route when it
        declares no block). ``hmp calibrate --list-phases`` and ``hmp config check``
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

    def _compares_a_record(self, phase: CalibPhaseDecl | None) -> bool:
        """Whether a search compares a dated record: a single metric, or a block on a station."""
        blocks = self._blocks_scored_by(phase)
        if not blocks:
            return True
        return any(
            getattr(self.outputs.get(str(name)), "observes", None)
            for block in blocks
            for name in block.uses_outputs
        )

    def validation_scored_by(self, phase: CalibPhaseDecl | None) -> bool:
        """Whether a search is scored on the validation window.

        A steady phase is not: its one state spans the steady window, not those dates. Nor
        is a search on a network or on typed values, which has no dated record to compare.
        """
        if self.validation_window is None or (phase is not None and phase.regime == "steady"):
            return False
        return self._compares_a_record(phase)

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
        """Whether a search is scored only by network distances left in meters.

        Read as :meth:`_criteria_scored_by` reads the criteria: a single-metric
        phase scores its own ``objective`` or the section's, and a search with
        no block scores the section's ``objective``. A block with a cost transform is
        no longer in meters, and neither is one with ``normalize_cost``, whose
        distance is counted in validity lengths. The single-metric route has
        neither.
        """
        from hydromodpy.calibration.criteria.registry import NETWORK_ESTIMATORS

        if phase is not None and phase.is_single_metric:
            return str(phase.objective or self.objective) in NETWORK_ESTIMATORS
        blocks = self._blocks_scored_by(phase)
        if not blocks:
            return str(self.objective) in NETWORK_ESTIMATORS
        return all(
            str(block.metric) in NETWORK_ESTIMATORS
            and block.cost_transform == "identity"
            and not block.normalize_cost
            for block in blocks
        )

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
                # the name is resolved against the project catalog once the whole
                # configuration is loaded. Until then the parameter's own name is
                # what a phase freezes. Two phases may freeze the same path: the
                # later one moves it again from the earlier value, and its value
                # wins. The staged report names both.
                path = self.parameters[parameter].resolve_target() or f"<{parameter}>"
                if phase.freeze_on_success:
                    frozen_by[path] = phase.name

            for problem in self.phase_bounds_problems(phase):
                raise ValueError(problem)

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

            if phase.method is None and phase.method_options:
                _check_the_method_takes_its_options(
                    f"phase {phase.name!r}", self.method, phase.method_options
                )
            if phase.depends_on is not None:
                if phase.depends_on not in seen[:index]:
                    raise ValueError(
                        f"phase {phase.name!r} depends on {phase.depends_on!r}, which is "
                        "not declared before it."
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
    def _check_a_margin_in_metres_has_a_distance_to_bound(self) -> CalibrationConfig:
        """Refuse a ``cost_margin`` in meters on a search that scores no network distance.

        A length bounds a cost that is itself a length. A phase that writes one
        and scores something else is refused; one that only inherits it from the
        section reads the default instead (:meth:`uncertainty_for`), and the
        section's own is refused when no search it covers scores distances.
        """
        searches: list[tuple[str, CalibPhaseDecl | None]] = [("[calibration.uncertainty]", None)]
        if self.phases:
            searches = [
                (f"phase {phase.name!r} uncertainty", phase)
                for phase in self.phases
                if phase.uncertainty is not None and phase.uncertainty.cost_margin is not None
            ]
        for where, phase in searches:
            own = self.uncertainty if phase is None else phase.uncertainty
            if own is None or own.cost_margin is None:
                continue
            if parse_cost_margin(own.cost_margin).kind != "absolute":
                continue
            if not self._scored_on_network_distances(phase):
                raise ValueError(_margin_in_metres_needs_distances(where, own.cost_margin))
        section = self.uncertainty.cost_margin
        if (
            self.phases
            and section is not None
            and parse_cost_margin(section).kind == "absolute"
            and not any(self._scored_on_network_distances(phase) for phase in self.phases)
        ):
            raise ValueError(
                _margin_in_metres_needs_distances("[calibration.uncertainty]", section)
            )
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
    def _refuse_an_objective_beside_blocks(self) -> CalibrationConfig:
        """Refuse a section ``objective`` written beside blocks, which score by their own metric.

        The block built from ``objective`` and ``variable`` is not a block the
        file wrote, so it passes.
        """
        implicit = [f"{self.objective}_{self.variable}"]
        if "objective" in self.model_fields_set and [b.name for b in self.objective_blocks] not in (
            [],
            implicit,
        ):
            raise ValueError(
                "objective is written beside [[calibration.objective_blocks]], which score "
                "by their own 'metric'; delete it, or delete the blocks to score one series."
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
            needs = criterion_for(str(block.metric)).requirements()
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
            readable.update(criterion_for(metric).requirements().reads_supports)
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
    def _refuse_outputs_the_station_route_leaves_aside(self) -> CalibrationConfig:
        """Refuse declared outputs when the file scores the loaded stations instead.

        Runs after the implicit block is built. With no block at all and a
        ``variable`` that names no output, the one-line form scores every
        loaded station of that variable, and an output declared beside it is
        never scored: the calibration fits the stations while the file reads as
        fitting the output, and ``hmp config check`` used to say OK. An output
        that blocks exist beside may still feed the residuals of a linearized
        width, and a network output on this route has its own refusal in the
        preflight, so both are left to those.
        """
        if not self.outputs or self.objective_blocks:
            return self
        named = {self.variable, *(phase.variable for phase in self.phases or () if phase.variable)}
        aside = sorted(
            name
            for name, output in self.outputs.items()
            if name not in named and str(output.support) != "network"
        )
        if not aside:
            return self
        raise ValueError(
            f"the output(s) {aside} are declared and nothing scores them: there is no "
            f"objective block, and variable = {self.variable!r} scores the stations the "
            "project loads. Write variable = '<output>' to score one of them, or declare "
            "[[calibration.objective_blocks]] that read them."
        )

    @model_validator(mode="after")
    def _check_the_validation_window(self) -> CalibrationConfig:
        """Refuse a validation window a cost could read, or that nothing would score.

        An open bound of a calibration window runs on to the end of the record, so it
        overlaps. A steady phase with no window of its own reads the record over its steady
        window, by default the whole run, when it compares a dated record.
        """
        if self.validation_window is None:
            return self
        first_day, last_day = window_bounds(self.validation_window)
        named = f"validation_window {first_day} to {last_day}"
        if first_day is None or last_day is None:
            raise ValueError(f"{named} leaves a bound open: write both start and end.")
        searches = self.phases or [None]
        if not any(self.validation_scored_by(search) for search in searches):
            raise ValueError(
                f"{named} has nothing to score: no transient search has a dated record."
            )
        for search in searches:
            window = getattr(search, "window", None) or self.window
            if window is None and getattr(search, "regime", None) == "steady":
                if not self._compares_a_record(search):
                    continue
                window = CalibWindow.model_validate(search.steady_window or {})
            start, end = window_bounds(window) or (None, None)
            if (start is None or start <= last_day) and (end is None or end >= first_day):
                raise ValueError(
                    f"{named} overlaps the window {start} to {end} of "
                    f"{getattr(search, 'name', '[calibration]')}, so a cost would read those "
                    "dates. Write a window that ends before it or starts after it."
                )
        return self

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


STATION_VARIABLES: tuple[str, ...] = ("discharge", "head", "lake_level")
"""The ``variable`` values the one-line form scores at the stations a project loads."""


def implicit_station_scoring(
    variable: str, objective: str, stations: list[str]
) -> tuple[dict[str, CalibOutputDecl], list[CalibObjectiveBlockDecl]]:
    """Return the output and the block ``variable`` + ``objective`` stand for, per station.

    The one-line form is scored by the block route: each station gets an
    output named ``<variable>@<station>`` that observes it, and a block named
    ``<objective>@<station>`` of weight one that reads it, so several stations
    average their costs. The stations are the ones the project loaded, known
    once the records are, not when the file is read. The burn-in and the window
    are the section's or the phase's: the block declares none of its own.
    """
    if variable not in STATION_VARIABLES:
        raise NotImplementedError(
            f"Calibration variable {variable!r} is scored at no loaded station. "
            f"Supported: {', '.join(STATION_VARIABLES)}, or the name of a "
            "[calibration.outputs] entry."
        )
    outputs: dict[str, CalibOutputDecl] = {}
    blocks: list[CalibObjectiveBlockDecl] = []
    for station in stations:
        name = f"{variable}@{station}"
        if variable == "lake_level":
            outputs[name] = CalibOutputLake(variable="stage", lake_id=station, observes=station)
        else:
            outputs[name] = CalibOutputPoint(variable=variable, observes=station)
        blocks.append(
            CalibObjectiveBlockDecl(
                name=f"{objective}@{station}", metric=objective, uses_outputs=[name]
            )
        )
    return outputs, blocks


def apply_project_defaults(
    section: Mapping[str, Any],
    *,
    site_gauge: str | None,
    metrics_window: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return the raw ``[calibration]`` table with the project-level defaults written in.

    ``[site] gauge`` is the station of the catchment: ``observes`` (on a point
    output) takes it when it is left unwritten, and a written value that names
    another station is refused with both keys. A point output that writes its own
    position (``x`` and ``y``, or ``geometry``) or its own ``observed_values``
    is left as written: the gauge neither locates it nor scores it.
    ``[metrics] window``, less ``validation_window``, is the default of ``window`` when the
    section writes no window. In a calibration with
    phases it goes on each phase that writes no window and is not steady, and it
    closes the end of a phase window that writes only a start,
    never on the section: a steady phase reads one state, stamped at the end
    of its steady window, which a window of dates over the record would leave
    out. Applied before validation, so a point output that names no station
    and no coordinates is valid in a project with a gauge.
    """
    from hydromodpy.core.site.config import resolve_gauge

    site = _site_of(site_gauge)
    payload: dict[str, Any] = dict(section)
    outputs = payload.get("outputs")
    if isinstance(outputs, Mapping):
        resolved_outputs: dict[str, Any] = {}
        for name, output in outputs.items():
            if _point_output_located_by_a_station(output):
                observes = resolve_gauge(
                    site, output.get("observes"), field=f"calibration.outputs.{name}.observes"
                )
                if observes is not None:
                    output = {**output, "observes": observes}
            resolved_outputs[name] = output
        payload["outputs"] = resolved_outputs
    window = window_of_the_run(metrics_window, payload.get("validation_window"))
    if payload.get("window") is None and window is not None:
        phases = payload.get("phases")
        if isinstance(phases, list) and phases:
            payload["phases"] = [_with_window(phase, window) for phase in phases]
        else:
            payload["window"] = window
    return payload


def window_of_the_run(metrics_window: Any, validation: Any = None) -> dict[str, str] | None:
    """Return a raw ``[metrics] window``, less a raw *validation* window, as a raw ``window``.

    ``None`` unless both bounds are written: a calibration window takes the
    run's only when the run is scored on a closed window.
    """
    if not isinstance(metrics_window, Mapping):
        return None
    start, end = metrics_window.get("start"), metrics_window.get("end")
    if start is None or end is None:
        return None
    window = {"start": str(start), "end": str(end)}
    return window if validation is None else _metrics_window_minus_validation(window, validation)


def _metrics_window_minus_validation(
    window: dict[str, str], validation: Any
) -> dict[str, str] | None:
    """Return a raw ``[metrics] window`` without its validation days, and refuse what cannot be.

    ``None`` when the validation window lies inside it with days on both sides: one window
    cannot say two spans, so nothing is written and the check on the section asks for one.
    A validation window that does not parse or leaves a bound open is left to that check too.
    """
    import pandas as pd

    try:
        first_day, last_day = window_bounds(CalibWindow.model_validate(validation))
    except ValidationError:
        return window
    if first_day is None or last_day is None:
        return window
    start, end = pd.Timestamp(window["start"]), pd.Timestamp(window["end"])
    if first_day < start or last_day > end or (first_day == start and last_day == end):
        raise ConfigValidationError(
            f"validation_window {first_day.date()} to {last_day.date()} has to lie inside "
            f"[metrics] window {start.date()} to {end.date()} and leave days to calibrate on."
        )
    one_day = pd.Timedelta(1, unit="D")
    if first_day == start:
        return {"start": (last_day + one_day).date().isoformat(), "end": window["end"]}
    if last_day == end:
        return {"start": window["start"], "end": (first_day - one_day).date().isoformat()}
    return None


def _with_window(phase: Any, window: dict[str, str]) -> Any:
    """Return a raw phase with *window* written in, unless it is steady.

    A phase with no window takes it whole. A window that writes only ``start`` is
    closed by the end of *window*, since a bound left open would otherwise end
    with ``[simulation.time]`` instead of ``[metrics] window``.
    """
    if not isinstance(phase, Mapping) or phase.get("regime") == "steady":
        return phase
    written = phase.get("window")
    if written is None:
        return {**phase, "window": dict(window)}
    if isinstance(written, Mapping) and written.get("end") is None:
        return {**phase, "window": {**written, "end": window["end"]}}
    return phase


def _point_output_located_by_a_station(output: Any) -> bool:
    """Whether a raw point output is located and scored by the station it observes.

    One that writes its own position (``x`` and ``y``, or ``geometry``) or
    its own ``observed_values`` is not: the gauge has nothing to give it.
    """
    if not isinstance(output, Mapping) or output.get("support") != "point":
        return False
    if output.get("observed_values") is not None:
        return False
    return not any(output.get(key) is not None for key in ("x", "y", "geometry"))


def _site_of(gauge: str | None) -> Any:
    """Return the smallest object :func:`resolve_gauge` reads a gauge from.

    ``resolve_gauge`` reads ``site.gauge`` and nothing else of the site. This
    function receives the gauge alone, from a raw document or from a project
    whose ``[site]`` is already a ``SiteConfig``, so it stands a nameless site
    in for the one the caller did not hand over.
    """
    if gauge is None:
        return None
    from hydromodpy.core.site import SiteConfig

    return SiteConfig(name="site", gauge=gauge)


__all__ = [
    "CalibrationConfig",
    "apply_project_defaults",
    "implicit_station_scoring",
    "STATION_VARIABLES",
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
    "window_of_the_run",
    "validate_calib_output",
]
