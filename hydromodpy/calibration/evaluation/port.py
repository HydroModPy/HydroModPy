"""What a calibration trial evaluator is: parameters in, a cost out.

Why an evaluator and not a forward model
----------------------------------------
A forward model hands back simulated values and something else scores them. That
is not what this repository can promise yet: the scoring path
(``calibration/metrics/composite.py``) does not read a vector, it reads the live
``WorkflowContext`` of the trial, through the solver adapter, the station-to-cell
mapping and ``extract_observables``. A port that advertised simulated outputs
would advertise a shape only the in-tree implementation could produce, which is
the disguise the criterion contract removed in F6.

So the port is drawn where the substitution is real: an evaluator receives one
parameter sample and returns one cost, which is exactly what the ask/tell loop
consumes. A surrogate, a lumped model, an emulator or a wrapper around a foreign
executable can all answer that. Making the criteria of
:mod:`hydromodpy.calibration.criteria` score a foreign model is the next step and
a larger one -- it is F9d, and it is what will let this port carry outputs.

What the loop actually reads
----------------------------
Measured, not assumed: :class:`~hydromodpy.calibration.optim.engine.CalibrationEngine`
reads ``trial_id`` and ``values`` off a suggestion, and branches on ``status`` and
``objective_value`` of a result. Everything else on ``EvaluationResult`` -- the
simulation id, the cache flag, the metadata -- is filled by the runner for
persistence and reporting, never by the loop. :class:`TrialOutcome` therefore
carries what the loop needs and what a report cannot reconstruct, and nothing
that belongs to the caller's bookkeeping.

The declaration that keeps a surrogate cheap
--------------------------------------------
``needs_prepared_model`` is read off the class, before anything is built. The
in-tree evaluator needs a prepared trial context, and preparing one runs the
whole geographic / mesh / data prefix of the pipeline -- minutes, and a DEM on
disk. An evaluator that answers ``False`` is not asked to pay for it. Without
this declaration a surrogate would still be preceded by the setup of the model it
replaces, which is not a surrogate.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import ClassVar, Literal, Protocol, runtime_checkable

TrialStatus = Literal["completed", "failed", "crashed"]
"""The three ends of a trial, the vocabulary ``TrialResult`` already uses.

``completed`` produced a finite cost. ``failed`` ran and could not be scored.
``crashed`` did not run. The loop treats the last two alike; a report does not,
which is why they stay apart here.
"""


@dataclass(frozen=True, slots=True)
class TrialRequest:
    """One parameter sample handed to an evaluator.

    ``trial_id`` is not decoration: the in-tree evaluator gives each trial its
    own sandbox folder keyed on it, so concurrent trials never share solver
    files, and a report names a candidate by it.

    ``values`` is not refused when empty, and that is measured rather than
    assumed: a configuration declaring no parameter builds an empty
    ``ParameterSpace``, and every optimizer of this repository then asks for a
    suggestion carrying ``{}``. Refusing it here would turn a degenerate
    calibration that used to run one unmodified trial into a crash, and the place
    to refuse a search with nothing to search is the document, not the port.
    """

    trial_id: int
    values: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class TrialOutcome:
    """What an evaluator found for one sample.

    ``cost`` is always to be minimised, the convention the criterion contract
    already states. A non-``completed`` outcome carries ``nan`` and says why in
    ``error``; returning a large finite number instead would let a failed trial
    win a search whose other trials were worse.
    """

    cost: float
    status: TrialStatus
    duration_s: float
    components: Mapping[str, float] = field(default_factory=dict)
    error: str | None = None


@runtime_checkable
class TrialEvaluator(Protocol):
    """A named way of turning a parameter sample into a cost.

    Implementations are resolved by name through
    :mod:`hydromodpy.calibration.evaluation.registry`. Nothing imports one: a
    document names it, and the registry answers.
    """

    evaluator_id: ClassVar[str]
    """Identifier written as ``[calibration].evaluator`` and stamped on a session."""

    needs_prepared_model: ClassVar[bool]
    """Whether this evaluator requires HydroModPy's own trial context.

    ``True`` means the caller runs ``prepare_trials`` first and passes the result
    as the ``trial_ctx`` option. ``False`` means it is never run, and the
    evaluator is built without it.
    """

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        """Return the cost of one sample. Never raises for a failed trial.

        A trial that cannot be scored comes back as a ``failed`` or ``crashed``
        outcome, because a search that raises on its first bad sample stops on a
        region of the space rather than walking out of it. An exception is
        reserved for what no sample can fix.
        """
        ...


def evaluator_members() -> tuple[str, ...]:
    """Return the member names :class:`TrialEvaluator` requires.

    Derived from the Protocol so a member added there is named by the registry's
    refusal without a second list to keep in step.
    """
    annotated = set(TrialEvaluator.__annotations__)
    defined = {
        name
        for name, value in vars(TrialEvaluator).items()
        if callable(value) and not name.startswith("_")
    }
    return tuple(sorted(annotated | defined))


__all__ = [
    "TrialEvaluator",
    "TrialOutcome",
    "TrialRequest",
    "TrialStatus",
    "evaluator_members",
]
