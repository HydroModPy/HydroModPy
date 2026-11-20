"""The phases of a calibration, their regime, their uncertainty and the aggregate block."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    AfterValidator,
    Field,
    field_validator,
    model_validator,
)

from hydromodpy.calibration.config_terms import (
    GAUGE_ADVICE,
    METRIC_VALUE_DOCS,
    CalibWindow,
    MetricKind,
    check_the_method_takes_its_options,
    never_read,
    renamed,
    renamed_to,
    validated_method_for,
)
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import (
    NonEmptyStr,
    PositiveFloat,
    PositiveInt,
)
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.plugin_registry import check_registered_name
from hydromodpy.core.scoring.cost_margin import parse_cost_margin

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


def margin_in_metres_needs_distances(where: str, text: str) -> str:
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
        **renamed(
            {
                "scoring_window": ("window", "the dates this phase scores"),
                "optimizer_kwargs": ("method_options", "options of this phase's method"),
                "max_iter": ("max_trials", "evaluations this phase may run"),
                "tolerance": ("precision", "how finely this phase pins its parameters"),
            }
        ),
        "observed_station_id": GAUGE_ADVICE,
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
        Annotated[str, AfterValidator(validated_method_for("calibration.phases.method"))] | None,
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
        json_schema_extra={"value_docs": METRIC_VALUE_DOCS},
    )
    method_options: Annotated[dict[str, Any] | None, Profile.USER] = Field(
        default=None,
        description="Options of this phase's method, named as that method names "
        "them: sweep_points for 'bisection', points_per_dim for 'grid', sampler for "
        "'optuna'. They belong to one method, so a phase that gives them writes "
        "method beside them, or runs the method [calibration] writes. Unset, the phase "
        "takes the method_options of [calibration] when it runs the method that section "
        "writes, and none otherwise; an empty table states that it takes none. A key "
        "the method does not take is refused when the file loads. hmp check "
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
            check_the_method_takes_its_options(
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
        **never_read("weighting", "nested_gauges", "on_member_failure"),
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
            "on the mesh it scores. A phase may write its own, which wins. hmp check "
            "refuses a share on a search scored only by network distances."
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


def registered_evaluator(value: str | None) -> str | None:
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
