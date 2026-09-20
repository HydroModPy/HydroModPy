"""What a forward model is: a parameter sample in, named observables out.

Why this port exists beside the evaluator one
---------------------------------------------
:mod:`hydromodpy.calibration.evaluation.port` draws the substitution where it
was real in F9a: parameters in, a cost out. Everything between the two -- which
quantity is compared to which record, under which criterion, with which weight
-- belonged to the implementation, so a foreign evaluator brought its own
scoring and a document could not change a criterion without patching it. The
in-tree wheel of F9c is the proof: ``hydromodpy-evaluator-reservoir`` hard-codes
its two observations and the mean of their squared relative residuals.

This port cuts one step earlier. A forward model answers with the observables it
was asked for, and the criteria of F6 -- the ``[calibration.outputs]`` and
``[[calibration.objective_blocks]]`` of the document -- score them through
:class:`~hydromodpy.calibration.metrics.observable_scoring.ObservableScorer`,
the context-free scorer F9d's first slice extracted. Changing a metric or a
weight is then a change to the document, and the model never learns about it.

The vocabulary is the solver's, on purpose
------------------------------------------
A request is a :class:`~hydromodpy.core.contracts.observables.ObservableRequest`
and an answer is an :class:`~hydromodpy.core.contracts.observables.ObservableResult`,
the same two classes a solver adapter already speaks. A foreign model therefore
joins on the contract the in-tree backends hold, and nothing new has to be
learnt or kept in step. ``id`` is the output name the document wrote, which is
what the scorer keys on.

What stays out of it, and why
-----------------------------
What a producer does to its own values is not in this port: locating a station
on a mesh, adding the runoff forcing to a drain budget, scaling it by the area
a cell drains, preparing the two distances of a stream network. Those are
transformations of one model's internals, they are measured in that model's own
terms, and the pipeline producer keeps every one of them. A port that carried
them would be advertising a shape only HydroModPy can produce, which is the
disguise F6 removed from the criteria and F9a from the evaluator.

Failure is an exception here, unlike the evaluator port
-------------------------------------------------------
A :class:`~hydromodpy.calibration.evaluation.port.TrialEvaluator` must never
raise: it is what the ask/tell loop calls, and an exception stops a search on a
region instead of walking out of it. A forward model is one level below, called
by the evaluator that composes it with the scorer, and that evaluator is what
turns a refusal into a ``failed`` outcome carrying ``nan``. So a model raises on
a sample it cannot run, which is the ordinary way to write one, and no
implementation has to reproduce the outcome discipline of the loop.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import ClassVar, Protocol, runtime_checkable

from hydromodpy.core.contracts.observables import ObservableRequest, ObservableResult


@dataclass(frozen=True, slots=True)
class ForwardRequest:
    """One parameter sample, and the observables the document asks for.

    ``values`` carries the sample in each parameter's own physical scale, the
    same mapping a :class:`~hydromodpy.calibration.evaluation.port.TrialRequest`
    carries -- an empty one is legal for the same reason, a document declaring
    no parameter.

    ``observables`` is derived from the declared outputs once, before the search,
    and is identical for every trial: what moves between trials is the sample,
    never what is asked of the model.
    """

    trial_id: int
    values: Mapping[str, float]
    observables: tuple[ObservableRequest, ...] = ()

    def wanted_ids(self) -> tuple[str, ...]:
        """Return the requested ids, in the order they were asked for."""
        return tuple(request.id for request in self.observables)


@dataclass(frozen=True, slots=True)
class ForwardOutcome:
    """What a forward model produced for one sample.

    ``observables`` is keyed by the ``id`` of the request it answers, so a model
    that serves two outputs of the same variable at two places keys them apart
    the way the document named them.

    ``diagnostics`` are reported beside the cost and never scored, the place a
    model puts what qualifies its run -- a mass balance error, an iteration
    count. They are merged into the trial components under the model's own
    spelling, so a name that collides with a criterion component is the model's
    to avoid.
    """

    observables: Mapping[str, ObservableResult]
    diagnostics: Mapping[str, float] = field(default_factory=dict)


@runtime_checkable
class ForwardModel(Protocol):
    """A named model that answers observable requests for a parameter sample.

    Implementations are resolved by name through
    :mod:`hydromodpy.calibration.evaluation.forward_registry`. Nothing imports
    one: a document names it, and the registry answers.
    """

    model_id: ClassVar[str]
    """Identifier written as ``[calibration].forward_model`` and recorded on a session."""

    def simulate(self, request: ForwardRequest) -> ForwardOutcome:
        """Return the observables of one sample, or raise saying why it cannot.

        Raising is how a sample is refused. The evaluator that composes this
        model with the document's criteria catches it and reports a ``failed``
        trial carrying ``nan``, so the search walks out of the region rather
        than stopping on it.

        A name the model cannot place is refused the same way, and not ignored:
        a model that quietly drops a parameter the document declared turns that
        knob into no knob at all, every sample of the search costs the same, and
        the report names a best that means nothing. The refusal is deliberate,
        which is to say it says which name it did not understand rather than
        surfacing as the ``KeyError`` of an unguarded lookup.
        """
        ...


def forward_model_members() -> tuple[str, ...]:
    """Return the member names :class:`ForwardModel` requires.

    Derived from the Protocol so a member added there is named by the registry's
    refusal without a second list to keep in step.
    """
    annotated = set(ForwardModel.__annotations__)
    defined = {
        name
        for name, value in vars(ForwardModel).items()
        if callable(value) and not name.startswith("_")
    }
    return tuple(sorted(annotated | defined))


def refuse_answers_nobody_asked_for(
    wanted: Sequence[str], answered: Mapping[str, ObservableResult], *, model_id: str
) -> None:
    """Hold an answer to the batch it answers: every id asked, and no other.

    A missing id is a model that cannot serve what the document declared, and a
    surplus one is a model and a document that disagree about a name -- scoring
    what is left would report a cost under a declaration that was not honoured.
    Both are the model's fault and both are named here rather than surfacing as
    a ``KeyError`` inside the scorer.
    """
    asked = list(dict.fromkeys(wanted))
    missing = [name for name in asked if name not in answered]
    if missing:
        served = ", ".join(sorted(answered)) or "nothing"
        raise ValueError(
            f"forward model {model_id!r} was asked for {', '.join(asked)} and served {served}: "
            f"no value for {', '.join(missing)}."
        )
    surplus = sorted(set(answered) - set(asked))
    if surplus:
        raise ValueError(
            f"forward model {model_id!r} answered {', '.join(surplus)}, which "
            f"{'is' if len(surplus) == 1 else 'are'} not among the outputs the document "
            f"declared ({', '.join(asked)}). An answer under a name nothing asked for is a "
            "model and a document that disagree about what is being scored."
        )
    mislabelled = sorted(
        name for name in asked if str(getattr(answered[name], "request_id", name)) != name
    )
    if mislabelled:
        pairs = ", ".join(f"{name} -> {answered[name].request_id!r}" for name in mislabelled)
        raise ValueError(
            f"forward model {model_id!r} keyed {pairs}: the key of an answer and the "
            "request_id it carries have to be the same id, otherwise a report names one "
            "output and a cost scores another."
        )


__all__ = [
    "ForwardModel",
    "ForwardOutcome",
    "ForwardRequest",
    "forward_model_members",
    "refuse_answers_nobody_asked_for",
]
