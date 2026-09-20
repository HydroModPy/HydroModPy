"""An evaluator with no model behind it, for rehearsing a calibration montage.

What it is for
--------------
A calibration is two things bolted together: a search -- parameter space,
optimizer, stopping rule, persistence, report -- and a model that answers it.
Until now the only way to find out whether the first half was wired correctly
was to run the second, which means a DEM, a mesh and a solver, and minutes per
trial. Naming this evaluator in ``[calibration] evaluator`` runs the whole
search in milliseconds over a closed-form surface, so a malformed space, an
optimizer that never moves, a stopping rule that fires at once or a report that
loses the best candidate all surface before a solver is ever built.

It is answerable, which is the point: the minimum sits at the **midpoint of each
parameter's transformed interval**, so a user who names this evaluator knows the
answer in advance and can tell a search that converged from a search that only
finished. On a log-transformed parameter that midpoint is the geometric mean of
the bounds, which is where the midpoint of a conductivity belongs.

What it computes
----------------
Every value in the sample is mapped onto ``[0, 1]`` across the transformed
bounds the space declares for it, and the cost is the mean squared distance from
:data:`BOWL_OPTIMUM`. Mean and not sum, so the scale of the cost does not depend
on how many parameters a document declares. The per-parameter terms come back as
``components``, which is what makes a rehearsal readable: one number per
dimension says which one the search is still far from.

What it refuses to invent
-------------------------
A sample naming a parameter the space does not declare, a value that is not a
finite number, and a value the parameter's own transform cannot take -- a
negative conductivity under a log transform -- come back as a ``failed`` outcome
carrying ``nan``, never as a finite cost. A failed trial that carries a number
can win a search whose other trials were worse, which is the one failure mode
this surface must not model. Each of the three is faced on the value itself,
before the interval is looked at, because a parameter pinned to one value has no
interval to be positioned on and would otherwise hand the optimum to the sample
that deserves it least. A parameter the space declares and the sample omits is
simply not scored: there is nothing to fabricate a value from.
"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace

BOWL_OPTIMUM = 0.5
"""Where the minimum sits, as a fraction of each transformed interval.

A constant and not an option: an evaluator's own settings have no place to be
written in a document yet, and inventing one here would give a calibration a
second configuration surface for the sake of a rehearsal.
"""


class AnalyticBowlEvaluator:
    """Score a sample against a quadratic bowl over the space being searched.

    Built by :func:`hydromodpy.calibration.evaluation.registry.create`, which
    binds ``space`` -- the only option this evaluator names. The space is not
    decoration: it carries the bounds and the transform each value has to be
    read against, and without it a cost would be a number about nothing.
    """

    evaluator_id: ClassVar[str] = "analytic_bowl"
    needs_prepared_model: ClassVar[bool] = False

    def __init__(self, *, space: ParameterSpace | None = None) -> None:
        # Optional in the signature and refused in the body, so a caller that
        # builds this evaluator without a space is told what a space is for
        # rather than shown a missing-argument error from the constructor.
        if space is None:
            raise ValueError(
                f"{self.evaluator_id!r} scores a sample against the bounds and the transform "
                "its parameters declare, so it is built with the space the search runs over. "
                "It was given none, and a cost computed without one would be a number about "
                "nothing."
            )
        self._space = space

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        """Return the mean squared distance to the optimum of the bowl."""
        started = time.perf_counter()
        components: dict[str, float] = {}
        for name, value in request.values.items():
            try:
                parameter = self._space[name]
            except KeyError:
                return self._failed(
                    started,
                    f"{name!r} is not a parameter of the space this evaluator was built with. "
                    f"It searches over {', '.join(self._space.names) or 'nothing'}.",
                )
            # The value is faced before the interval is, and that order is the
            # whole of it: a parameter pinned to one value has no interval, so a
            # position read first would return the optimum for a sample that
            # cannot be read at all -- a nan or a negative conductivity would
            # come back as the best cost the surface has.
            #
            # Three exception classes and not two: ``float(10**400)`` raises
            # OverflowError, and moving this conversion out of the block that
            # reads the position is exactly how it stops being caught. A sample a
            # search cannot score must not leave here as an exception, whatever
            # the spelling of the value.
            try:
                sample = float(value)
            except (TypeError, ValueError, OverflowError):
                return self._failed(started, f"{name}={value!r} is not a number this can read.")
            if not math.isfinite(sample):
                return self._failed(started, f"{name}={value!r} is not a finite number.")
            try:
                position = _unit_position(parameter, sample)
            except (ValueError, OverflowError) as exc:
                return self._failed(
                    started,
                    f"{name}={value!r} cannot be read against its own "
                    f"{parameter.transform!r} transform: {exc}",
                )
            if not math.isfinite(position):
                return self._failed(
                    started, f"{name}={value!r} does not land anywhere on the declared interval."
                )
            try:
                component = (position - BOWL_OPTIMUM) ** 2
            except OverflowError:
                return self._failed(started, f"{name}={value!r} has an unrepresentable cost.")
            if not math.isfinite(component):
                return self._failed(started, f"{name}={value!r} has an unrepresentable cost.")
            components[name] = component
        # No terms is not an error: a document declaring no parameter builds an
        # empty space, and every optimizer of this repository then asks for one
        # suggestion carrying nothing. It costs zero, and the rehearsal is that
        # the montage ran.
        try:
            cost = (
                math.fsum(component / len(components) for component in components.values())
                if components
                else 0.0
            )
        except OverflowError:
            return self._failed(started, "The mean cost cannot be represented.")
        if not math.isfinite(cost):
            return self._failed(started, "The mean cost cannot be represented.")
        return TrialOutcome(
            cost=cost,
            status="completed",
            duration_s=time.perf_counter() - started,
            components=components,
        )

    def _failed(self, started: float, reason: str) -> TrialOutcome:
        """A trial that could not be scored, carrying ``nan`` and saying why."""
        return TrialOutcome(
            cost=math.nan,
            status="failed",
            duration_s=time.perf_counter() - started,
            error=reason,
        )


def _unit_position(parameter: CalibParameter, value: float) -> float:
    """Return where *value* sits on ``[0, 1]`` across the transformed bounds.

    A parameter whose bounds coincide has no width to be positioned on, so it
    sits at the optimum and contributes nothing: pinning a value is how a
    document takes a dimension out of a search, not how it makes it expensive.
    The transform is still applied first, and it still raises on a value it
    cannot take -- a pinned dimension takes a sample out of the cost, never out
    of the checks.
    """
    position = parameter.to_transformed(value)
    low = parameter.lower_transformed
    high = parameter.upper_transformed
    span = high - low
    if span == 0.0:
        return BOWL_OPTIMUM
    return (position - low) / span


__all__ = ["BOWL_OPTIMUM", "AnalyticBowlEvaluator"]
