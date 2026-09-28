"""One-dimensional root search driven by the sign of a residual.

Every other adapter here minimises a cost. This one brackets a sign change and
closes the bracket, because the criterion it serves has a root rather than a
minimum: the balance between an excess of simulated stream and a missing one is
where the signed gap crosses zero, and a cost that only knows ``abs`` of it
cannot tell which side it is on.

Three things follow from the measured shape of that residual, and each one is a
line of code here.

The function is not continuous. The masks are discrete, so the two averages
jump when a cell switches, and the residual steps over zero rather than
reaching it: on a real catchment ``abs(J)`` never drops below three metres
while the root is bracketed to a factor 1.0015. **The stopping rule is
therefore the width of the bracket, never the size of the residual.** A search
that stops on ``abs(J) < eps`` may never stop at all.

Monotonicity is not proven. The paper establishes the direction of variation on
three points and generalises it; the coarse sweep run before the bisection
checks it instead of assuming it, sees every crossing rather than one, and
comes out of the same solves as the diagnostic curves the method publishes.

A bracket that never changes sign is a result, not an accident to paper over.
Returning the better of the two ends would be a minimised mean distance in
disguise, which is exactly the drift this whole criterion exists to correct, so
the adapter raises and prints both residuals.

The budget is known before the first solve (:func:`root_search_budget`). With
``d`` the declared interval in decades, ``t = log10(1 + rel_tol)``, ``S`` sweep
points (two when ``sweep_points`` is zero), ``s = d / (S - 1)`` the sweep step
and ``E = bracket_expand``:

- a root inside the declared bounds costs ``N_nominal = S + ceil(log2(s / t))``;
- a root found after ``e`` expansions costs ``S + 2e + ceil(log2(1 / t))``, since
  each expansion evaluates two new ends and leaves a bracket one decade wide;
- ``N_worst`` is the largest of those, reached at ``e = E`` whenever the sweep
  step is at most a decade.

On the Nancon, [1e-7, 1e-3] m/s, seven sweep points and one per cent: 15
evaluations inside the bounds, 17, 19, 21 and 23 after one to four expansions.
``max_iter = "auto"`` budgets 23; a declared 10 is refused before the first
solve; 20, the default before ``"auto"``, covers two expansions. When a budget
still runs out, the adapter publishes the halvings its bracket still needs
(:attr:`BisectionAdapter.evaluations_remaining`), and the engine grants exactly
those, once.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from hydromodpy.calibration.optim.optimizer import (
    EngineTraits,
    EvaluationResult,
    ParamSuggestion,
    register_optimizer,
)
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.calibration.optim.stopping import CountedBudget
from hydromodpy.core.exceptions import ObjectiveError, OptimizerError
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

LOG10_ONE_PERCENT = 4.32137e-3
"""``log10(1.01)``: the paper's "K/R varies by less than one per cent", written
in the log variable the search actually walks."""

DEFAULT_REL_TOL = 0.01
"""The paper's one per cent on K/R."""

DEFAULT_SWEEP_POINTS = 7
"""Points of the coarse log sweep run before the bisection."""

DEFAULT_BRACKET_EXPAND = 4
"""Decade-wide expansions on both sides allowed before a missing root is refused."""

_DEFAULT_SIGNED_COMPONENT = "J_signed"


def _same_cost(first: float, second: float) -> bool:
    """Two costs a float round-off apart are one cost."""
    return math.isclose(first, second, rel_tol=1e-9, abs_tol=1e-12)


def _halvings(width: float, tolerance: float) -> int:
    """Return how many halvings bring a bracket *width* wide to *tolerance*."""
    if width <= tolerance:
        return 0
    return math.ceil(math.log2(width / tolerance))


def _sweep_size(sweep_points: int) -> int:
    """Return how many points the sweep evaluates: the two bounds when it is zero."""
    return 2 if sweep_points <= 0 else max(2, int(sweep_points))


def _budget_in_log_space(
    width: float, tolerance: float, sweep_points: int, bracket_expand: int
) -> CountedBudget:
    """Count the evaluations for an interval *width* decades wide, per expansion."""
    points = _sweep_size(sweep_points)
    nominal = points + _halvings(width / (points - 1), tolerance)
    after_one_decade = _halvings(1.0, tolerance)
    expanded = [
        points + 2 * expansions + after_one_decade
        for expansions in range(1, max(0, int(bracket_expand)) + 1)
    ]
    return CountedBudget(counts=(nominal, *expanded))


def root_search_budget(
    lower: float,
    upper: float,
    *,
    rel_tol: float = DEFAULT_REL_TOL,
    sweep_points: int = DEFAULT_SWEEP_POINTS,
    bracket_expand: int = DEFAULT_BRACKET_EXPAND,
) -> CountedBudget:
    """Return the evaluations the root search needs, per bracket expansion.

    ``lower`` and ``upper`` are the declared bounds in physical units. With ``d``
    the interval in decades, ``t = log10(1 + rel_tol)``, ``S`` the sweep points
    (two when zero) and ``s = d / (S - 1)``:
    ``nominal = S + ceil(log2(s / t))``, a root found after ``e`` expansions
    costs ``S + 2e + ceil(log2(1 / t))``, and ``worst`` is the largest count.
    On the Nancon, [1e-7, 1e-3] with seven points and one per cent, the counts
    are 15, 17, 19, 21 and 23.
    """
    low, high = float(lower), float(upper)
    if not (0.0 < low < high):
        raise ValueError(
            f"a root search on a log parameter needs 0 < lower < upper, got [{low}, {high}]."
        )
    if float(rel_tol) <= 0.0:
        raise ValueError(f"rel_tol must be strictly positive, got {rel_tol}.")
    return _budget_in_log_space(
        math.log10(high) - math.log10(low),
        math.log10(1.0 + float(rel_tol)),
        int(sweep_points),
        int(bracket_expand),
    )


def signed_residual(
    components: Mapping[str, float] | None,
    *,
    name: str = _DEFAULT_SIGNED_COMPONENT,
) -> float | None:
    """Read the signed residual out of a trial's components.

    A network output prefixes its diagnostics with its own name, so the lookup
    accepts both the bare key and any ``<output>.<key>`` form; two outputs
    publishing the same residual is a declaration error and says so.
    """
    if not components:
        return None
    if name in components:
        return float(components[name])
    suffix = f".{name}"
    matches = [key for key in components if key.endswith(suffix)]
    if not matches:
        return None
    if len(matches) > 1:
        raise OptimizerError(
            f"several outputs publish a {name!r} residual ({sorted(matches)}); a root "
            "search needs exactly one."
        )
    return float(components[matches[0]])


@register_optimizer("bisection")
class BisectionAdapter:
    """Bracket the sign change of a residual, then close the bracket."""

    name = "bisection"

    traits = EngineTraits(
        max_parameters=1,
        required_transform="log",
        needs_signed_residual=True,
        supports_parallel=False,
        restarts_explore_differently=False,
        tolerance_option="rel_tol",
        tolerance_reads="relative_value",
    )
    """The same three refusals the constructor makes, readable before it runs."""

    def __init__(
        self,
        space: ParameterSpace,
        *,
        seed: int | None = None,
        rel_tol: float = DEFAULT_REL_TOL,
        signed_component: str = _DEFAULT_SIGNED_COMPONENT,
        sweep_points: int = DEFAULT_SWEEP_POINTS,
        bracket_expand: int = DEFAULT_BRACKET_EXPAND,
    ) -> None:
        del seed  # a root search is deterministic
        if space.dim != 1:
            raise OptimizerError(
                "the bisection adapter searches one parameter; the space declares "
                f"{space.dim} ({', '.join(space.names)}). A two-parameter space silently "
                "bisected along its first axis is the worst failure this method has."
            )
        parameter = space.parameters[0]
        if parameter.transform != "log":
            raise OptimizerError(
                f"the bisection adapter walks a log10 variable, but parameter "
                f"{parameter.name!r} declares transform = {parameter.transform!r}. Its "
                "stopping rule is a width in that variable, so on any other transform it "
                "reads as an absolute width and reports convergence on a bracket orders "
                'of magnitude wide. Declare transform = "log" for this parameter.'
            )
        if float(rel_tol) <= 0.0:
            raise OptimizerError(f"rel_tol must be strictly positive, got {rel_tol}.")
        if int(sweep_points) < 0:
            raise OptimizerError(f"sweep_points must be positive or zero, got {sweep_points}.")

        self.space = space
        self._parameter = parameter
        self._signed_component = str(signed_component)
        self._sweep_points = int(sweep_points)
        self._max_expansions = max(0, int(bracket_expand))
        # The paper's relative criterion on K/R becomes an absolute width in the
        # log variable, which is what the search actually halves.
        self._tolerance = math.log10(1.0 + float(rel_tol))

        self._declared = (
            float(self._parameter.lower_transformed),
            float(self._parameter.upper_transformed),
        )
        self._low = float(self._parameter.lower_transformed)
        self._high = float(self._parameter.upper_transformed)
        self._history: list[EvaluationResult] = []
        self._residuals: dict[int, float] = {}
        self._points: dict[int, float] = {}
        self._pending: list[float] = self._initial_points()
        self._expansions = 0
        self._bracket: tuple[float, float] | None = None
        self._done = False
        self._trial_id = 0

    # -- planning ----------------------------------------------------------- #

    def _initial_points(self) -> list[float]:
        """The first points to evaluate: a coarse sweep, or the two bounds."""
        if self._sweep_points <= 0:
            return [self._low, self._high]
        count = max(2, self._sweep_points)
        step = (self._high - self._low) / (count - 1)
        return [self._low + step * index for index in range(count)]

    def _evaluated(self) -> list[tuple[float, float]]:
        """Return ``(x, residual)`` for every usable evaluation, x ascending."""
        pairs = [
            (self._points[trial], self._residuals[trial])
            for trial in self._residuals
            if trial in self._points and math.isfinite(self._residuals[trial])
        ]
        return sorted(pairs)

    def _find_bracket(self) -> tuple[float, float] | None:
        """Return the tightest pair of consecutive points that change sign."""
        pairs = self._evaluated()
        found: list[tuple[float, float]] = []
        for (x_low, r_low), (x_high, r_high) in zip(pairs[:-1], pairs[1:], strict=False):
            if r_low == 0.0:
                return (x_low, x_low)
            if r_low * r_high < 0.0:
                found.append((x_low, x_high))
        if not found:
            return None
        if len(found) > 1:
            logger.warning(
                "The residual changes sign %d times over the sweep, so the root is not "
                "unique on this interval. The tightest crossing is the one closed; the "
                "sweep curve is worth reading before trusting the value.",
                len(found),
            )
        return min(found, key=lambda pair: pair[1] - pair[0])

    def _expand(self) -> bool:
        """Widen the interval by one decade on both sides. False when exhausted."""
        if self._expansions >= self._max_expansions:
            return False
        self._expansions += 1
        self._low -= 1.0
        self._high += 1.0
        self._pending = [self._low, self._high]
        logger.info(
            "No sign change yet: widening the bracket to [%.3f, %.3f] in log space "
            "(expansion %d of %d).",
            self._low,
            self._high,
            self._expansions,
            self._max_expansions,
        )
        return True

    def _refuse(self) -> None:
        """Raise, naming both ends, rather than returning the better of the two."""
        pairs = self._evaluated()
        if not pairs:
            raise OptimizerError(
                "the bisection adapter has no usable residual: every evaluation failed. "
                f"Check that the outputs publish a {self._signed_component!r} component."
            )
        (x_low, r_low), (x_high, r_high) = pairs[0], pairs[-1]
        name = self._parameter.name
        raise OptimizerError(
            "the residual keeps the same sign over the whole bracket: "
            f"{self._signed_component} = {r_low:+.4g} at {name} = "
            f"{self._parameter.to_physical(x_low):.4g}, and {r_high:+.4g} at {name} = "
            f"{self._parameter.to_physical(x_high):.4g}. There is no root to close here. "
            "Returning the better of the two ends would be a minimised mean distance in "
            "disguise, so the search stops instead."
        )

    def _plan_after_batch(self) -> None:
        """Decide what to evaluate next, once a batch has been told."""
        if self._pending:
            return
        bracket = self._find_bracket()
        if bracket is None:
            if any(result.status != "completed" for result in self._history):
                # A failed end means the surface, not the interval: widening it
                # would only buy more failures.
                self._done = True
                self._refuse()
            if not self._expand():
                self._done = True
                self._refuse()
            return
        self._bracket = bracket
        low, high = bracket
        if high - low <= self._tolerance:
            self._done = True
            return
        self._pending = [0.5 * (low + high)]

    # -- the ask / tell contract -------------------------------------------- #

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        """Return up to ``n`` points, or nothing when the bracket is closed."""
        if self._done:
            return []
        out: list[ParamSuggestion] = []
        while self._pending and len(out) < max(1, int(n)):
            x = self._pending.pop(0)
            self._trial_id += 1
            self._points[self._trial_id] = x
            out.append(
                ParamSuggestion(
                    trial_id=self._trial_id,
                    values={self._parameter.name: float(self._parameter.to_physical(x))},
                    source="sweep" if self._bracket is None else "bisect",
                )
            )
        return out

    def suggest_next(self) -> ParamSuggestion:
        points = self.ask(1)
        if not points:
            raise OptimizerError("the bisection adapter has nothing left to suggest.")
        return points[0]

    def tell(self, results: Sequence[EvaluationResult]) -> None:
        """Record the residual of each evaluation, then plan the next batch."""
        for result in results:
            self._history.append(result)
            residual = signed_residual(result.components, name=self._signed_component)
            if residual is None:
                if result.status == "completed":
                    raise ObjectiveError(
                        f"trial {result.trial_id} published no {self._signed_component!r} "
                        "component, so its sign is unknown and a root search is blind. "
                        "Declare a network output, whose criterion emits it."
                    )
                continue
            self._residuals[result.trial_id] = float(residual)
        self._plan_after_batch()

    def best(self) -> EvaluationResult | None:
        """Return the evaluated trial closest to the root, inside the bracket.

        The cost carries ``abs`` of the residual, so the lowest cost is the
        trial nearest zero. What is returned is a point that was really
        evaluated, never the middle of the last interval: every quantity the
        method publishes beside the value has to come from a real solve.

        The bracket is where the root is, so the answer is taken inside it.
        The residual steps rather than slides, so two trials often share one
        ``abs(J)`` to the last digit, and ``min`` then returned the first one
        evaluated, which can sit outside the final bracket: on the Nancon,
        trial 13 tied with trial 15 and was returned 0.6 % outside
        [2.0783e-4, 2.0908e-4]. Among trials inside the bracket the lowest cost
        wins, and a tie goes to the trial nearest its middle, the best estimate
        of the root the search holds. A trial outside is returned only when no
        completed trial lies inside, which happens when a rejected trial set an
        end, and that says so.
        """
        valid = [result for result in self._history if result.status == "completed"]
        if not valid:
            return None
        winner = self._pick(valid)
        self._warn_if_outside_the_declared_bounds(winner)
        return winner

    def _pick(self, valid: list[EvaluationResult]) -> EvaluationResult:
        """Choose among completed trials, preferring those inside the bracket."""
        inside = [result for result in valid if self._inside_bracket(result.trial_id)]
        pool = inside or valid
        lowest = min(result.objective_value for result in pool)
        tied = [result for result in pool if _same_cost(result.objective_value, lowest)]
        if self._bracket is None:
            return tied[0]
        middle = 0.5 * (self._bracket[0] + self._bracket[1])
        winner = min(
            tied, key=lambda result: abs(self._points.get(result.trial_id, middle) - middle)
        )
        if not inside:
            low, high = self._bracket
            logger.warning(
                "No completed trial lies inside the final bracket [%.4g, %.4g] of %s: its "
                "ends come from rejected trials. Trial %d, outside it, is returned.",
                self._parameter.to_physical(low),
                self._parameter.to_physical(high),
                self._parameter.name,
                winner.trial_id,
            )
        return winner

    def _inside_bracket(self, trial_id: int) -> bool:
        """Whether a trial was evaluated inside the current bracket, ends included."""
        if self._bracket is None:
            return False
        x = self._points.get(trial_id)
        if x is None:
            return False
        low, high = self._bracket
        slack = 1e-12 * max(1.0, abs(low), abs(high))
        return low - slack <= x <= high + slack

    def _warn_if_outside_the_declared_bounds(self, winner: EvaluationResult) -> None:
        """Say it when the root only exists outside the interval that was declared.

        The search widens its bracket by a decade at a time, which is what lets
        it find a sign change a cautious prior missed. But a root several decades
        outside the declared bounds is usually not a surprising conductivity: it
        is the residual failing to respond to the parameter at all. Measured on
        the Nancon with the streams in SFR, the simulated network holds the
        reaches by construction whatever the conductivity, the residual stays
        positive across the whole declared interval, and the search closes on a
        value three decades above it that means nothing.
        """
        if self._expansions == 0:
            return
        transformed = self._points.get(winner.trial_id)
        if transformed is None:
            return
        low, high = self._declared
        if low <= float(transformed) <= high:
            return
        value = self._parameter.to_physical(float(transformed))
        lower = self._parameter.to_physical(low)
        upper = self._parameter.to_physical(high)
        logger.warning(
            "The root closed on %s = %.4g, OUTSIDE the declared bounds [%.4g, %.4g], after "
            "%d bracket expansion(s). Either the prior was too narrow, or the residual does "
            "not respond to this parameter over the declared range: a simulated network "
            "holding cells that are prescribed rather than computed never retracts, and the "
            "search then balances against that fixed skeleton. Check n_excess at the low end "
            "of the sweep: it should collapse as the parameter rises.",
            self._parameter.name,
            float(value),
            lower,
            upper,
            self._expansions,
        )

    def converged(self) -> bool:
        """Whether the bracket is closed: no wider than the tolerance.

        ``_done`` alone is not enough. A refusal also sets it before raising, with
        no bracket ever found, and a caller that catches that error must not read
        the search as converged.
        """
        return self._bracket is not None and self._done

    @property
    def counted_budget(self) -> CountedBudget:
        """Evaluations the declared bounds, sweep and tolerance need, per expansion.

        Read by the engine before the first solve: ``"auto"`` budgets its worst
        case, a budget below its nominal case is refused. See
        :func:`root_search_budget`.
        """
        low, high = self._declared
        return _budget_in_log_space(
            high - low, self._tolerance, self._sweep_points, self._max_expansions
        )

    @property
    def evaluations_remaining(self) -> int | None:
        """Halvings the current bracket still needs, or None before one is found.

        ``ceil(log2(width / t))``, zero once the bracket is closed. Before a sign
        change the sweep or an expansion is still running, and what follows it
        is not known yet.
        """
        if self._bracket is None:
            return None
        if self._done:
            return 0
        low, high = self._bracket
        return _halvings(high - low, self._tolerance)

    @property
    def bracket(self) -> tuple[float, float] | None:
        """The latest bracket in the transformed variable, closed or not.

        Set as soon as a sign change is found and narrowed by each step;
        :meth:`converged` says whether it reached the tolerance.
        """
        return self._bracket

    def bracket_record(self) -> dict[str, Any] | None:
        """Return the final bracket for the report, or None before a sign change.

        ``low`` and ``high`` are in the parameter's physical units and
        ``relative_width`` is ``high / low - 1``, the number ``rel_tol`` is read
        against. ``closed`` is False when the budget ran out first: the root is
        still inside, only less precisely than asked. The paper publishes no
        such interval; it is what the search itself proved, which the tolerance
        interval on the trials does not.
        """
        if self._bracket is None:
            return None
        low, high = self._bracket
        return {
            "parameter": self._parameter.name,
            "low": float(self._parameter.to_physical(low)),
            "high": float(self._parameter.to_physical(high)),
            "relative_width": float(10.0 ** (high - low) - 1.0),
            "closed": self.converged(),
        }


__all__ = [
    "DEFAULT_BRACKET_EXPAND",
    "DEFAULT_REL_TOL",
    "DEFAULT_SWEEP_POINTS",
    "LOG10_ONE_PERCENT",
    "BisectionAdapter",
    "root_search_budget",
    "signed_residual",
]
