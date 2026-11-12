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

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    AfterValidator,
    Field,
    ValidationError,
    model_validator,
)

from hydromodpy.calibration.config_objective import (
    CalibObjectiveBlockDecl,
    CalibParameterDecl,
    CalibrationProtocolDecl,
)
from hydromodpy.calibration.config_outputs import CalibOutputDecl, CalibOutputLake, CalibOutputPoint
from hydromodpy.calibration.config_phases import (
    CalibAggregateDecl,
    CalibPhaseDecl,
    CalibUncertaintyDecl,
    margin_in_metres_needs_distances,
    registered_evaluator,
)
from hydromodpy.calibration.config_terms import (
    GAUGE_ADVICE,
    METRIC_VALUE_DOCS,
    THIS_TABLE,
    CalibrationMethod,
    CalibWindow,
    MetricKind,
    PersistIterationDetail,
    SaveRunsMode,
    check_the_method_takes_its_options,
    never_read,
    renamed,
    window_bounds,
)
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import (
    PositiveFloat,
    PositiveInt,
)
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.scoring.cost_margin import parse_cost_margin
from hydromodpy.schema.changes import prerelease_refusal


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
        **renamed(
            {
                "scoring_window": ("window", "the dates every metric is scored on"),
                "optimizer_kwargs": ("method_options", "options of the method"),
                "max_iter": ("max_trials", "the evaluations the search may run"),
                "tolerance": ("precision", "how finely the search pins a parameter"),
            }
        ),
        "observed_station_id": GAUGE_ADVICE,
        "warmup_periods": (
            "write window = {start = <date>} instead, with [simulation.time] "
            "start_datetime plus that many steps as the date. "
            + prerelease_refusal(THIS_TABLE, ["warmup_periods"])
        ),
        # Declared and never read. The promoted run follows
        # [simulation.results.persistence], never these.
        **never_read("lightweight_extraction", "persist_model_distribution", "persistence"),
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
    evaluator: Annotated[str | None, Profile.USER, AfterValidator(registered_evaluator)] = Field(
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
        json_schema_extra={"value_docs": METRIC_VALUE_DOCS},
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
        "as a small Parquet table per trial under the session folder, about 2 kB per "
        "trial on the island case. Network "
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
        from hydromodpy.calibration.criteria.registry import criterion_for

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
        check_the_method_takes_its_options("[calibration]", self.method, self.method_options)
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
        ``hmp check`` refuses it on an engine that stops on its budget. The
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
        declares no block). ``hmp calibrate --list-phases`` and ``hmp check``
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
                check_the_method_takes_its_options(
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
                raise ValueError(margin_in_metres_needs_distances(where, own.cost_margin))
        section = self.uncertainty.cost_margin
        if (
            self.phases
            and section is not None
            and parse_cost_margin(section).kind == "absolute"
            and not any(self._scored_on_network_distances(phase) for phase in self.phases)
        ):
            raise ValueError(margin_in_metres_needs_distances("[calibration.uncertainty]", section))
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
        from hydromodpy.calibration.criteria.registry import criterion_for

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
        from hydromodpy.calibration.criteria.registry import available_criteria, criterion_for

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
        fitting the output, and ``hmp check`` used to say OK. An output
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
    from hydromodpy.core.site.config import SiteConfig

    return SiteConfig(name="site", gauge=gauge)


__all__ = [
    "STATION_VARIABLES",
    "CalibrationConfig",
    "apply_project_defaults",
    "implicit_station_scoring",
    "window_of_the_run",
]
