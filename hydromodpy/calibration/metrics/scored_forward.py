"""The evaluator that puts a foreign model under the document's own criteria.

It owns no physics and no metric. It resolves the model
``[calibration] forward_model`` names, asks it for the observables
``[calibration.outputs]`` declares, and hands the answer to the scorer built
from ``[[calibration.objective_blocks]]``. So the two halves a calibration is
made of come from two places that do not know each other: what is simulated
from an installed distribution, how it is scored from the file.

That separation is what F9d is for. Under the evaluator port alone, a foreign
implementation returned a cost, which means it also chose what was compared and
how it was weighed -- such an evaluator hard-codes the observations it compares
and the metric applied to them, and changing either means editing the wheel. Here, changing a metric or a weight is an edit
to the document and the model is not rebuilt.

What it refuses, and why it refuses early
-----------------------------------------
Three declarations have no meaning on this route, and each is refused at
construction rather than at the first trial:

- an output naming a station through ``observes``, because the record is loaded
  from the project's data families and this evaluator declares it needs no
  prepared model -- there is no project to load it from;
- an output on ``support = "network"``, because the pair of distances it scores
  is prepared from a routed mesh by the pipeline producer, not by a model;
- an output on ``support = "point"``, or a cell named by a flat ``cell_id``,
  because both are resolved against a mesh this route does not build.

A window is refused too, by the scorer itself: without ``observes`` nothing here
carries a date to cut on. So is a record of a length no answer to this
declaration could ever have -- one value scored against three is unscorable for
every sample and not for an unlucky one. The refusals are the frontier of the
route, they all leave the same exit code, and they say what to declare instead.

What it holds an answer to
--------------------------
The ids it asked for and no others, and the number of values each output is
scored on. The second is checked output by output rather than on the total,
because a block concatenates its outputs before it compares: two answers whose
lengths are individually wrong and whose sum is right would otherwise be paired
across the boundary between them and reported as a completed trial.

A model's diagnostics are recorded under a ``diagnostic.`` prefix. They travel
beside the cost and are never scored, and the prefix is what keeps a model from
overwriting what the criteria say about themselves -- the point of the port is
that the model does not get to speak about the score.

What is not checked yet
-----------------------
The unit an answer carries is recorded and not verified. An output scored
positionally is compared to ``observed_values`` typed into the document, which
carries no unit either, so there is nothing here to check one against. It stays
a named limit of the frontier rather than a silent conversion.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

import hydromodpy.calibration.evaluation.forward_registry as forward_registry
from hydromodpy.calibration.config import scoring_window_bounds
from hydromodpy.calibration.evaluation.forward import (
    ForwardRequest,
    refuse_answers_nobody_asked_for,
)
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
from hydromodpy.calibration.metrics.observable_scoring import (
    ObservableScorer,
    select_observable_times,
    slice_time,
)
from hydromodpy.calibration.metrics.observed_pairing import observing_outputs
from hydromodpy.core.contracts.observables import (
    ObservableRequest,
    ObservableResult,
    TimeSelector,
    require_unique_request_ids,
)
from hydromodpy.core.exceptions import CalibrationError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path

    from hydromodpy.calibration.config import CalibOutputDecl, CalibrationConfig

EVALUATOR_ID = "scored_forward_model"
"""What a document writes in ``[calibration] evaluator`` to take this route."""


class ScoredForwardEvaluator:
    """Score a named forward model with the criteria the document declares.

    Built by :func:`hydromodpy.calibration.evaluation.registry.create`. It names
    four of the construction options: the configuration it reads its criteria
    and its model name from, and the three it passes on to the model's own
    constructor without looking at them.
    """

    evaluator_id: ClassVar[str] = EVALUATOR_ID
    needs_prepared_model: ClassVar[bool] = False

    def __init__(
        self,
        *,
        cfg: CalibrationConfig | None = None,
        space: Any | None = None,
        workspace: Path | None = None,
        cfg_path: Path | None = None,
    ) -> None:
        if cfg is None:
            raise CalibrationError(
                f"{EVALUATOR_ID!r} scores a model with the criteria the document declares, so "
                "it is built with that document. It was given none."
            )
        outputs = dict(getattr(cfg, "outputs", None) or {})
        blocks = list(getattr(cfg, "objective_blocks", None) or [])
        if not outputs or not blocks:
            raise CalibrationError(
                f"{EVALUATOR_ID!r} asks a model for the outputs [calibration.outputs] declares "
                "and scores them with [[calibration.objective_blocks]]; this document declares "
                f"{len(outputs)} output(s) and {len(blocks)} block(s). Both are what this "
                "evaluator is for: without them there is nothing to ask for and nothing to "
                "weigh."
            )
        self._outputs = outputs
        self._requests = requests_for_outputs(outputs)
        refuse_a_length_no_sample_can_match(outputs)
        try:
            self._scorer = ObservableScorer(
                outputs,
                blocks,
                observed_records=None,
                warmup_periods=int(getattr(cfg, "warmup_periods", 0) or 0),
                scoring_window=scoring_window_bounds(getattr(cfg, "scoring_window", None)),
                min_samples=int(getattr(getattr(cfg, "aggregate", None), "min_samples", 1) or 1),
            )
        # A window with no dated output is the fifth refusal of this route, and
        # the scorer states it as a bare ValueError. Retyped here so the six
        # refusals of a document leave the same exit code as one another
        # instead of one of them falling through as a generic failure.
        except ValueError as exc:
            raise CalibrationError(str(exc)) from exc
        self._model_id = forward_registry.resolve_id(getattr(cfg, "forward_model", None))
        self._model = forward_registry.create(
            getattr(cfg, "forward_model", None),
            cfg=cfg,
            space=space,
            workspace=workspace,
            cfg_path=cfg_path,
        )

    @property
    def forward_model_id(self) -> str:
        """The id of the model this evaluator resolved, default included."""
        return self._model_id

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        """Run the model on one sample and score its answer with the document."""
        started = time.perf_counter()
        try:
            outcome = self._model.simulate(
                ForwardRequest(
                    trial_id=request.trial_id,
                    values=dict(request.values),
                    observables=self._requests,
                )
            )
            refuse_answers_nobody_asked_for(
                [observable.id for observable in self._requests],
                outcome.observables,
                model_id=self._model_id,
            )
            refuse_a_shape_the_document_cannot_score(
                self._outputs, outcome.observables, model_id=self._model_id
            )
            cost, components = self._scorer.score(
                outcome.observables,
                diagnostics={
                    f"diagnostic.{name}": value for name, value in outcome.diagnostics.items()
                },
            )
        # Every exception, because a model refuses a sample by raising and the
        # loop must not stop on a region of the space. What no sample can fix is
        # refused in the constructor, before a search is started.
        except Exception as exc:
            return self._failed(started, f"{type(exc).__name__}: {exc}")
        if not math.isfinite(cost):
            return self._failed(started, f"the cost of this sample is {cost!r}.")
        return TrialOutcome(
            cost=float(cost),
            status="completed",
            duration_s=time.perf_counter() - started,
            components={str(name): float(value) for name, value in components.items()},
        )

    def _failed(self, started: float, reason: str) -> TrialOutcome:
        """A trial that could not be scored, carrying ``nan`` and saying why."""
        return TrialOutcome(
            cost=math.nan,
            status="failed",
            duration_s=time.perf_counter() - started,
            error=f"forward model {self._model_id!r}: {reason}",
        )


def requests_for_outputs(
    outputs: Mapping[str, CalibOutputDecl],
) -> tuple[ObservableRequest, ...]:
    """Turn the declared outputs into the batch a forward model is asked for.

    The id of a request is the name the document gave the output, which is what
    the scorer keys on, so a model answers in the document's own vocabulary.

    A declaration that cannot be placed without a mesh or a project is refused
    by name: this route builds neither, and a request that quietly dropped the
    placement would be scored as though the model had honoured it.
    """
    observing = observing_outputs(outputs)
    if observing:
        named = ", ".join(f"{name} -> {station}" for name, station in sorted(observing.items()))
        raise CalibrationError(
            f"output(s) {named} name a station through 'observes', and a record is loaded from "
            "the project's data families. This route runs a model that declares it needs no "
            "prepared project, so there is nothing to load it from: score them on "
            "'observed_values', or calibrate them through the pipeline evaluator."
        )
    requests: list[ObservableRequest] = []
    for name, output in outputs.items():
        support = str(getattr(output, "support", ""))
        if support == "network":
            raise CalibrationError(
                f"output {name!r} is a stream network, whose pair of distances is prepared "
                "from a routed mesh by the pipeline producer and not by a forward model. It "
                "has no meaning on a model scored from a document."
            )
        if support == "point":
            raise CalibrationError(
                f"output {name!r} is placed at a planar point, which is resolved against a "
                "mesh this route does not build. Place it on the cell or the boundary the "
                "model names."
            )
        cell: tuple[int, int, int] | None = None
        if support == "cell":
            row = getattr(output, "row", None)
            col = getattr(output, "col", None)
            if row is None or col is None:
                raise CalibrationError(
                    f"output {name!r} names cell_id={getattr(output, 'cell_id', None)!r}, a "
                    "flat index resolved against a mesh this route does not build. Declare "
                    "'row' and 'col'."
                )
            cell = (int(getattr(output, "layer", 0) or 0), int(row), int(col))
        key = getattr(output, "boundary_id", None) or getattr(output, "lake_id", None)
        requests.append(
            ObservableRequest(
                id=str(name),
                name=str(getattr(output, "variable", "") or ""),
                support=support,  # type: ignore[arg-type]  # refused above unless mappable
                key=None if key is None else str(key),
                cell=cell,
                times=_time_selector(getattr(output, "time", "all")),
            )
        )
    require_unique_request_ids(requests)
    return tuple(requests)


def served_length(output: CalibOutputDecl) -> int | None:
    """Return how many values an answer is scored on, when the document fixes it.

    ``time = "first"`` or ``"last"`` keeps one value, and an aggregating reducer
    folds whatever it receives into one. In both cases the count is a property of
    the declaration and not of the answer, so a record of another length can
    never be matched -- ``None`` when the length depends on what the model
    serves.
    """
    if str(getattr(output, "reducer", "none")) in ("mean", "sum", "last"):
        return 1
    return 1 if getattr(output, "time", "all") in ("first", "last") else None


def refuse_a_length_no_sample_can_match(outputs: Mapping[str, CalibOutputDecl]) -> None:
    """Refuse a record no answer of this declaration could ever pair with.

    An output that is scored on one value and typed against three is unscorable
    for every sample, not for an unlucky one: the search would run its whole
    budget, fail every trial and report no best cost at all. What no sample can
    fix belongs here, before anything is started.
    """
    for name, output in outputs.items():
        observed = getattr(output, "observed_values", None)
        served = served_length(output)
        if not observed or served is None or len(observed) == served:
            continue
        raise CalibrationError(
            f"output {name!r} is scored on {served} value(s) -- time="
            f"{getattr(output, 'time', 'all')!r}, reducer={getattr(output, 'reducer', 'none')!r} "
            f"-- and declares {len(observed)} observed value(s). No sample can pair the two, so "
            "a search on this document would fail every trial: type one observed value, or "
            "score the output on 'all' with a reducer that keeps its series."
        )


def refuse_a_shape_the_document_cannot_score(
    outputs: Mapping[str, CalibOutputDecl],
    observables: Mapping[str, ObservableResult],
    *,
    model_id: str,
) -> None:
    """Hold an answer to the length of the record it is scored against.

    A block naming two outputs concatenates before it compares, so two answers
    whose lengths are individually wrong but sum to the right total are paired
    across the boundary between them and scored as though both had matched. The
    count is checked here, output by output, on the values the scorer will
    actually use, so the trial fails saying which output is wrong instead of
    reporting a cost computed over a pairing nobody declared.
    """
    for name, output in outputs.items():
        observed = getattr(output, "observed_values", None)
        result = observables.get(name)
        if not observed or result is None:
            continue
        selected = select_observable_times(result, getattr(output, "time", "all"))
        served = len(slice_time(selected.values, "all", str(getattr(output, "reducer", "none"))))
        if served == len(observed):
            continue
        raise ValueError(
            f"output {name!r} is scored against {len(observed)} observed value(s) and "
            f"{model_id!r} served {served}. Lengths are compared per output because a block "
            "concatenates its outputs before it scores them, where two wrong lengths adding up "
            "to the right total pair values across the boundary between two outputs."
        )


def _time_selector(time: Any) -> TimeSelector:
    """Return the selector a request carries for a declared ``time``.

    A list of explicit dates comes back as ``"all"``, which is what the historical
    path does with it as well (D224): the selection then happens on values, and an
    undated answer has no timestamp to match a date against. Kept identical rather
    than fixed here, because fixing it changes numbers that already exist.
    """
    return time if time in ("all", "first", "last") else "all"


__all__ = [
    "EVALUATOR_ID",
    "ScoredForwardEvaluator",
    "refuse_a_length_no_sample_can_match",
    "refuse_a_shape_the_document_cannot_score",
    "requests_for_outputs",
    "served_length",
]
