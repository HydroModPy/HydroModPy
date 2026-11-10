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
report a search that honored a request it never read.

The same declaration tells the engine loop why a search stopped, in one of
three states (:data:`~hydromodpy.results.record.checks.StopState`). An engine that
names a stopping option met it (``rule_met``) or ran out of budget first
(``budget_spent``): its answer is then wherever the budget happened to end. An
engine that sweeps a design it counts up front, the grid and the Latin
hypercube, solved every point of it (``plan_exhausted``) or was cut short by
its budget, which is not its design either. Only the first two are
convergence. An engine that names no option has no rule of its own: it
spends its budget by design (``budget_spent``), unless a rule of its own
options ends it first. It did not converge, but there was no rule to miss, so
its answer may still be built on (:func:`settled`), and the caller says so.

The budget itself follows the same logic. An engine that can count the
evaluations its rule needs, before the first solve, publishes that count
(:class:`CountedBudget`): ``max_trials = "auto"`` then budgets its worst case, a
declared number below its nominal case is refused, and at run time the engine
is granted exactly what it says it still needs, once. An engine that cannot
count gets no extension: a search stopped by its budget is reported as not
converged, and a re-run of the same file with a larger ``max_trials`` replays the
trials already solved from the params-hash cache.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from hydromodpy.calibration.optim.optimizer import EngineTraits, engine_traits
from hydromodpy.results.record.checks import BUDGET_RULE, StopState

PRECISION_FIELD = "calibration.precision"
"""Where the precision is declared, for the message an engine refusal prints."""


def stopping_rule(optimizer: Any) -> str:
    """Name the rule *optimizer* stops on: its stopping option, its design, or ``"budget"``.

    Read on the instance, from the traits its class declares, because the engine
    loop holds an optimizer and not the name it was built from. An engine with
    no stopping option that counts its evaluations up front sweeps a design,
    and its rule is to solve every point of it.
    """
    traits = getattr(optimizer, "traits", None)
    if isinstance(traits, EngineTraits) and traits.precision_option is not None:
        return traits.precision_option
    counted = getattr(optimizer, "counted_budget", None)
    if isinstance(counted, CountedBudget):
        return f"every {counted.step}"
    return BUDGET_RULE


def stop_state(optimizer: Any, *, met: bool, spent: bool) -> StopState:
    """Return why *optimizer* stopped, from whether it met its rule and spent its budget.

    *met* is what the engine says of itself (``converged()``), *spent* whether
    the budget, extension included, is used up. An engine with a stopping
    option or a counted design is judged on *met* alone. An engine with no
    rule of its own that used its whole budget spent it, whatever it says:
    its own end then only coincides with the budget.
    """
    if stopping_rule(optimizer) == BUDGET_RULE:
        return "rule_met" if met and not spent else "budget_spent"
    if not met:
        return "budget_spent"
    traits = getattr(optimizer, "traits", None)
    if isinstance(traits, EngineTraits) and traits.precision_option is not None:
        return "rule_met"
    return "plan_exhausted"


def settled(state: StopState, rule: str) -> bool:
    """Whether the answer of a search that stopped in *state* may be built on.

    This is the one rule a staged calibration freezes by, and a session closes
    ``completed`` by. A search that met its rule or exhausted its plan
    settled. So did a search with no rule of its own that spent its budget:
    its best trial is the best of a budget-only search, and the caller says
    so. A search that spent its budget before a rule it has did not.
    """
    return state != "budget_spent" or rule == BUDGET_RULE


AUTO_BUDGET = "auto"
"""The ``max_trials`` that asks the engine to size its own budget."""

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

    def steps_covered(self, max_trials: int) -> int:
        """Return how many steps *max_trials* covers, each one and all before it."""
        covered = 0
        for index, count in enumerate(self.counts[1:], start=1):
            if count > max_trials:
                break
            covered = index
        return covered


def resolve_budget(optimizer: Any, max_trials: int | str) -> int:
    """Return the evaluation budget *optimizer* runs with.

    An integer is taken as written. ``"auto"`` is the worst case of an engine
    that publishes a :class:`CountedBudget` as ``counted_budget``, and
    :data:`UNCOUNTED_BUDGET` for any other engine.
    """
    if max_trials == AUTO_BUDGET:
        counted = getattr(optimizer, "counted_budget", None)
        if isinstance(counted, CountedBudget):
            return counted.worst
        return UNCOUNTED_BUDGET
    if isinstance(max_trials, str):
        raise ValueError(f'max_trials is a positive integer or "auto", got {max_trials!r}.')
    return int(max_trials)


def budget_kwargs(method: str, max_trials: int | str) -> dict[str, Any]:
    """Return the budget an engine that sizes itself on it is built with, or nothing.

    Only an engine that declares ``takes_max_trials`` is handed it, as its
    ``max_trials``; ``"auto"`` is resolved as for any engine that cannot count.
    """
    if not engine_traits(method).takes_max_trials:
        return {}
    return {"max_trials": resolve_budget(None, max_trials)}


def short_budget(
    counted: CountedBudget, max_trials: int
) -> tuple[Literal["error", "warning"], str] | None:
    """Judge a declared budget against what the engine counted, before any solve.

    Below the nominal count the search cannot meet its rule even when the answer
    is where the file said, so it is an error. Between the nominal and the worst
    count it is a warning that says how many steps the budget covers. A design
    has a single count, one evaluation per point.
    """
    budget = int(max_trials)
    if budget >= counted.worst:
        return None
    if len(counted.counts) == 1:
        return "error", (
            f"max_trials = {budget} is below the {counted.nominal} evaluations of this "
            f"search, one per {counted.step}, and a sweep cut short is not its design. "
            f'Write max_trials = "auto" ({counted.nominal} here), or ask for fewer points '
            "in method_options."
        )
    if budget < counted.nominal:
        return "error", (
            f"max_trials = {budget} is below the {counted.nominal} evaluations this search "
            f"needs to meet its stopping rule even with no {counted.step}. Write "
            f'max_trials = "auto" ({counted.worst} here, its worst case), or at least '
            f"{counted.nominal}."
        )
    steps = len(counted.counts) - 1
    return "warning", (
        f"max_trials = {budget} covers {counted.steps_covered(budget)} {counted.step}(s) "
        f"of the {steps} the search may take; the worst case needs {counted.worst}. "
        f'max_trials = "auto" budgets that.'
    )


def remaining_grant(remaining: Any, max_trials: int) -> int:
    """Return the evaluations granted once when the budget ends before the rule.

    *remaining* is what the engine says it still needs, and it is granted exactly,
    never a fraction of the budget. Nothing is granted when the engine cannot
    count it, or when it exceeds half the budget: a search that far from its rule
    is a configuration to fix, not a budget to stretch in silence.
    """
    if not isinstance(remaining, int) or isinstance(remaining, bool) or remaining <= 0:
        return 0
    if remaining > math.ceil(int(max_trials) / 2):
        return 0
    return remaining


def stopping_kwargs(
    method: str,
    space: Any,
    *,
    precision: float | None,
    declared: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the engine kwargs with *precision* written in the engine's own option.

    ``declared`` is what the file wrote under ``method_options``, which stays
    the escape hatch for reproducing a published call in the engine's own units.
    Stating both the precision and the option it writes is refused: two numbers
    for one rule, silently ranked, is how a configuration stops meaning what it
    says.
    """
    kwargs = dict(declared or {})
    if precision is None:
        return kwargs

    value = float(precision)
    if value <= 0.0:
        raise ValueError(f"{PRECISION_FIELD} must be strictly positive, got {value!r}.")

    traits = engine_traits(method)
    option = traits.precision_option
    if option is None:
        raise ValueError(
            f"{PRECISION_FIELD} asks {method!r} to stop at a precision on the "
            "parameter, and that engine has no such rule: it stops on its "
            "evaluation budget, or on the spread of its own population. Set "
            "max_trials to say how long it may run, or run a phase on an engine "
            "that converges on the parameter ('bisection', 'scipy_nelder_mead')."
        )
    if option in kwargs:
        raise ValueError(
            f"{PRECISION_FIELD} and method_options.{option} both set the "
            f"stopping rule of {method!r}. Keep one: the precision, read on the "
            "parameter, or the engine's own option, which reproduces a published "
            "call verbatim."
        )
    kwargs[option] = engine_stopping_value(method, space, precision=value)
    if option == "xatol" and "fatol" not in kwargs:
        # The simplex also stops on the spread of its costs. Left at an absolute
        # 1e-4 it depends on the units of the cost, so it follows the precision.
        kwargs.update(fatol=0.0, fatol_rel=value)
    return kwargs


def engine_stopping_value(method: str, space: Any, *, precision: float) -> float:
    """Return what *method* wants written in its stopping option for *precision*."""
    traits = engine_traits(method)
    reads = traits.precision_reads
    if reads == "relative_value":
        # The option is already a relative width on the parameter's own value, and
        # the engine declaring it walks log10, so the number carries over.
        return float(precision)
    if reads == "search_width":
        return _narrowest_search_width(space, precision)
    raise ValueError(
        f"engine {method!r} names {traits.precision_option!r} as its stopping rule "
        "without declaring how that option reads its number; set precision_reads "
        "in its EngineTraits."
    )


def _narrowest_search_width(space: Any, precision: float) -> float:
    """Return the strictest per-parameter width, in the space the search walks.

    One number stops the search for every parameter at once, so the precision has
    to be the one that satisfies all of them, which is the smallest.
    """
    widths = [search_width(parameter, precision) for parameter in getattr(space, "parameters", ())]
    if not widths:
        raise ValueError(
            f"{PRECISION_FIELD} is a precision on a parameter, and the search space declares none."
        )
    return min(widths)


def search_width(parameter: Any, precision: float) -> float:
    """Return *precision* as a width in the variable the search walks.

    On a parameter searched in log space a relative precision is a ratio, and the search
    variable is the decade, so the width is exact and needs no bound at all: a
    conductivity known to ten per cent is 0.0414 decades wide wherever it sits. On
    any other search space there is no scale on the value to be relative to before
    the search has a value, so the declared interval is the scale.
    """
    if getattr(parameter, "search_space", "identity") == "log":
        return math.log10(1.0 + float(precision))
    low = float(parameter.lower_transformed)
    high = float(parameter.upper_transformed)
    return float(precision) * abs(high - low)


__all__ = [
    "AUTO_BUDGET",
    "PRECISION_FIELD",
    "UNCOUNTED_BUDGET",
    "CountedBudget",
    "budget_kwargs",
    "remaining_grant",
    "resolve_budget",
    "short_budget",
    "engine_stopping_value",
    "search_width",
    "settled",
    "stop_state",
    "stopping_kwargs",
    "stopping_rule",
]
