"""One statement of precision, whatever engine walks the search.

Nine engines stop for nine different reasons and name the rule nine different
ways: a relative bracket width for the root search, ``xatol`` in the transformed
variable for the simplex, a spread of population energies for differential
evolution. Asking a hydrogeologist which of those they meant is asking the wrong
person: what they know is how precisely they need the conductivity, and that
sentence has to survive a change of engine.

So the file states the precision once, on the parameter, and each engine declares
in its traits which of its own options that writes and in which units. An engine
whose stopping rule is a budget and not a precision declares nothing, and a
precision handed to it is refused rather than dropped: silently ignoring it would
report a search that honoured a request it never read.

The same declaration tells the engine loop what "converged" means. An engine
that names a stopping option can run out of budget before meeting it, and that
search did not converge: its answer is wherever the budget happened to end. An
engine that names none stops on its budget by design, so spending it is its
rule and not a failure.

The budget itself follows the same logic. An engine that can count the
evaluations its rule needs, before the first solve, publishes that count
(:class:`CountedBudget`): ``max_iter = "auto"`` then budgets its worst case, a
declared number below its nominal case is refused, and at run time the engine
is granted exactly what it says it still needs, once. An engine that cannot
count gets no extension: a search stopped by its budget is reported as not
converged, and a re-run with a larger ``max_iter`` replays the trials already
solved from the params-hash cache.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from hydromodpy.calibration.optim.optimizer import EngineTraits, engine_traits

TOLERANCE_FIELD = "calibration.tolerance"
"""Where the precision is declared, for the message an engine refusal prints."""

BUDGET_RULE = "budget"
"""The rule of an engine that declares no stopping option: it stops on max_iter."""


def stopping_rule(optimizer: Any) -> str:
    """Name the rule *optimizer* stops on: its stopping option, or ``"budget"``.

    Read on the instance, from the traits its class declares, because the engine
    loop holds an optimizer and not the name it was built from.
    """
    traits = getattr(optimizer, "traits", None)
    if isinstance(traits, EngineTraits) and traits.tolerance_option is not None:
        return traits.tolerance_option
    return BUDGET_RULE


AUTO_BUDGET = "auto"
"""The ``max_iter`` that asks the engine to size its own budget."""

UNCOUNTED_BUDGET = 100
"""What ``"auto"`` budgets for an engine that cannot count its evaluations."""


@dataclass(frozen=True)
class CountedBudget:
    """The evaluations an engine needs to meet its rule, counted before the first solve.

    ``counts[e]`` is what the search spends when its answer needs ``e`` steps of
    ``step`` beyond the declared setting. For the root search a step is one
    bracket expansion: ``counts[0]`` is a root inside the declared bounds,
    ``counts[e]`` a root found after ``e`` expansions.
    """

    counts: tuple[int, ...]
    step: str = "bracket expansion"

    @property
    def nominal(self) -> int:
        """Evaluations when the answer lies where the file said: ``counts[0]``."""
        return self.counts[0]

    @property
    def worst(self) -> int:
        """The most the engine can spend before it meets its rule or refuses."""
        return max(self.counts)

    def steps_covered(self, max_iter: int) -> int:
        """Return how many steps *max_iter* covers, each one and all before it."""
        covered = 0
        for index, count in enumerate(self.counts[1:], start=1):
            if count > max_iter:
                break
            covered = index
        return covered


def resolve_budget(optimizer: Any, max_iter: int | str) -> int:
    """Return the evaluation budget *optimizer* runs with.

    An integer is taken as written. ``"auto"`` is the worst case of an engine
    that publishes a :class:`CountedBudget` as ``counted_budget``, and
    :data:`UNCOUNTED_BUDGET` for any other engine.
    """
    if max_iter == AUTO_BUDGET:
        counted = getattr(optimizer, "counted_budget", None)
        if isinstance(counted, CountedBudget):
            return counted.worst
        return UNCOUNTED_BUDGET
    if isinstance(max_iter, str):
        raise ValueError(f'max_iter is a positive integer or "auto", got {max_iter!r}.')
    return int(max_iter)


def short_budget(
    counted: CountedBudget, max_iter: int
) -> tuple[Literal["error", "warning"], str] | None:
    """Judge a declared budget against what the engine counted, before any solve.

    Below the nominal count the search cannot meet its rule even when the answer
    is where the file said, so it is an error. Between the nominal and the worst
    count it is a warning that says how many steps the budget covers.
    """
    budget = int(max_iter)
    if budget >= counted.worst:
        return None
    if budget < counted.nominal:
        return "error", (
            f"max_iter = {budget} is below the {counted.nominal} evaluations this search "
            f"needs to meet its stopping rule even with no {counted.step}. Write "
            f'max_iter = "auto" ({counted.worst} here, its worst case), or at least '
            f"{counted.nominal}."
        )
    steps = len(counted.counts) - 1
    return "warning", (
        f"max_iter = {budget} covers {counted.steps_covered(budget)} {counted.step}(s) "
        f"of the {steps} the search may take; the worst case needs {counted.worst}. "
        f'max_iter = "auto" budgets that.'
    )


def remaining_grant(remaining: Any, max_iter: int) -> int:
    """Return the evaluations granted once when the budget ends before the rule.

    *remaining* is what the engine says it still needs, and it is granted exactly,
    never a fraction of the budget. Nothing is granted when the engine cannot
    count it, or when it exceeds half the budget: a search that far from its rule
    is a configuration to fix, not a budget to stretch in silence.
    """
    if not isinstance(remaining, int) or isinstance(remaining, bool) or remaining <= 0:
        return 0
    if remaining > math.ceil(int(max_iter) / 2):
        return 0
    return remaining


def stopping_kwargs(
    method: str,
    space: Any,
    *,
    tolerance: float | None,
    declared: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the engine kwargs with *tolerance* written in the engine's own option.

    ``declared`` is what the file wrote under ``optimizer_kwargs``, which stays
    the escape hatch for reproducing a published call in the engine's own units.
    Stating both the precision and the option it writes is refused: two numbers
    for one rule, silently ranked, is how a configuration stops meaning what it
    says.
    """
    kwargs = dict(declared or {})
    if tolerance is None:
        return kwargs

    value = float(tolerance)
    if value <= 0.0:
        raise ValueError(f"{TOLERANCE_FIELD} must be strictly positive, got {value!r}.")

    traits = engine_traits(method)
    option = traits.tolerance_option
    if option is None:
        raise ValueError(
            f"{TOLERANCE_FIELD} asks {method!r} to stop at a precision on the "
            "parameter, and that engine has no such rule: it stops on its "
            "evaluation budget, or on the spread of its own population. Set "
            "max_iter to say how long it may run, or run a phase on an engine "
            "that converges on the parameter ('bisection', 'scipy_nelder_mead')."
        )
    if option in kwargs:
        raise ValueError(
            f"{TOLERANCE_FIELD} and optimizer_kwargs.{option} both set the "
            f"stopping rule of {method!r}. Keep one: the precision, read on the "
            "parameter, or the engine's own option, which reproduces a published "
            "call verbatim."
        )
    kwargs[option] = engine_stopping_value(method, space, tolerance=value)
    return kwargs


def engine_stopping_value(method: str, space: Any, *, tolerance: float) -> float:
    """Return what *method* wants written in its stopping option for *tolerance*."""
    traits = engine_traits(method)
    reads = traits.tolerance_reads
    if reads == "relative_value":
        # The option is already a relative width on the parameter's own value, and
        # the engine declaring it walks log10, so the number carries over.
        return float(tolerance)
    if reads == "search_width":
        return _narrowest_search_width(space, tolerance)
    raise ValueError(
        f"engine {method!r} names {traits.tolerance_option!r} as its stopping rule "
        "without declaring how that option reads its number; set tolerance_reads "
        "in its EngineTraits."
    )


def _narrowest_search_width(space: Any, tolerance: float) -> float:
    """Return the strictest per-parameter width, in the space the search walks.

    One number stops the search for every parameter at once, so the precision has
    to be the one that satisfies all of them, which is the smallest.
    """
    widths = [search_width(parameter, tolerance) for parameter in getattr(space, "parameters", ())]
    if not widths:
        raise ValueError(
            f"{TOLERANCE_FIELD} is a precision on a parameter, and the search space declares none."
        )
    return min(widths)


def search_width(parameter: Any, tolerance: float) -> float:
    """Return *tolerance* as a width in the variable the search walks.

    On a log-transformed parameter a relative precision is a ratio, and the search
    variable is the decade, so the width is exact and needs no bound at all: a
    conductivity known to ten per cent is 0.0414 decades wide wherever it sits. On
    any other transform there is no scale on the value to be relative to before
    the search has a value, so the declared interval is the scale.
    """
    if getattr(parameter, "transform", "identity") == "log":
        return math.log10(1.0 + float(tolerance))
    low = float(parameter.lower_transformed)
    high = float(parameter.upper_transformed)
    return float(tolerance) * abs(high - low)


__all__ = [
    "AUTO_BUDGET",
    "BUDGET_RULE",
    "TOLERANCE_FIELD",
    "UNCOUNTED_BUDGET",
    "CountedBudget",
    "remaining_grant",
    "resolve_budget",
    "short_budget",
    "engine_stopping_value",
    "search_width",
    "stopping_kwargs",
    "stopping_rule",
]
