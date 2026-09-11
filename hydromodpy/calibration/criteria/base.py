"""What a criterion is, and what it has to say about itself.

An objective used to be a function ``f(sim, obs) -> float``. That signature fits
a series and nothing else, so a criterion comparing a simulated stream network to
a mapped one had to disguise itself as one: a two-element vector standing in for a
series, an observed vector of zeros standing in for observations it does not have,
and a free-text component name standing in for "this criterion publishes a signed
residual". Five artefacts existed to hold one shape open.

A criterion declares what it needs and returns what it found. Two consequences,
and they are the point:

Declaring the needs makes them checkable BEFORE a solver runs. Whether a cost
has a unit decides if normalising it means anything; whether it carries a signed
residual decides if a root search may be pointed at it. Both were discovered at
the first trial, hours in.

Returning a structure means the meaning of a number travels with it. A cost is
always to be minimised. A signed residual is present or it is ``None``, not a
component name a caller hopes is right. Validity qualifies a result without
penalising it, which is the rule the whole calibration surface rests on: a
calibration is asked for a number, and a coarse agreement is said, not scored.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class CriterionRequirements:
    """What a criterion needs, and what its cost is.

    Read before the first solve. Every field answers a question that used to be
    answered by a crash.
    """

    needs_observations: bool
    """Whether an observed record has to be supplied. A criterion balancing two
    simulated quantities needs none, and asking for one produced the vector of
    zeros this contract exists to remove."""

    has_time_axis: bool
    """Whether the values it scores carry timestamps. A burn-in in samples and a
    scoring window in dates both need one; without it they are refused by name
    rather than applied to something that has no time in it."""

    signed: bool
    """Whether the cost IS the absolute value of a signed residual it publishes.
    Only then may a root search be pointed at it: a bracket closes on the zero of
    the residual and reports the smallest cost as its best, and the two agree
    only by construction."""

    cost_is_dimensionless: bool
    """Whether the cost is already a pure number. An efficiency score is; a
    residual in metres is not. Dividing a dimensionless cost by the standard
    deviation of its own observations does not put two blocks on a common
    footing, it reweights one of them in silence."""

    cost_unit: str | None = None
    """The unit of the cost when it has one, for a report that has to say it."""


@dataclass(frozen=True)
class Validity:
    """One check that qualifies a result without penalising it.

    ``passed`` is the verdict, ``message`` is the sentence a reader who is not a
    hydrogeologist needs: what the failure does to the number that was returned.
    A validity never enters the cost. That is the rule, and it is why a
    calibration under a coarse agreement still returns a value.
    """

    name: str
    passed: bool
    value: float | None
    message: str
    fatal: bool = False
    """True for the few checks that make the number a fiction rather than coarse."""


@dataclass(frozen=True)
class CriterionResult:
    """What a criterion found.

    ``cost`` is always to be minimised, whatever the sign convention of the
    underlying score.
    """

    cost: float
    signed_residual: float | None = None
    validity: tuple[Validity, ...] = ()
    diagnostics: Mapping[str, float] = field(default_factory=dict)

    @property
    def is_fatally_invalid(self) -> bool:
        """Whether a check said the number is a fiction rather than coarse."""
        return any(check.fatal and not check.passed for check in self.validity)


@runtime_checkable
class Criterion(Protocol):
    """A named way of turning evidence into a cost.

    Implementations live in this package and are resolved by name through
    :mod:`hydromodpy.calibration.criteria.registry`. Nothing imports one
    directly: a file names it, and the registry answers.
    """

    name: str

    def requirements(self) -> CriterionRequirements:
        """Return what this criterion needs and what kind of cost it produces."""
        ...

    def score(
        self,
        simulated: Sequence[float] | Any,
        observed: Sequence[float] | Any | None = None,
    ) -> CriterionResult:
        """Return the cost and everything that qualifies it."""
        ...


__all__ = [
    "Criterion",
    "CriterionRequirements",
    "CriterionResult",
    "Validity",
]
