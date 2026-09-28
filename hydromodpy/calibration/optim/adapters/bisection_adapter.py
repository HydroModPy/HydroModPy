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

**Two roots.** A network output scored on two bounds (``n_bounds_scored = 2``:
a transient extent table and a minimal map) publishes one residual per bound,
``J_signed_minimal`` and ``J_signed_maximal``, and no ``J_signed``. The search
then sweeps once, keeps one bracket per bound on the same trials, and halves
each until its width reaches the tolerance. The value it returns is the
weighted geometric mean of the two roots,
``log K = w_min log K*_min + w_max log K*_max``, with the weights the output
publishes (``weight_minimal``, ``weight_maximal``). That value is evaluated
once more, so every number published beside it comes from a real solve; the
two roots and their spread ``Delta = log10(K*_max / K*_min)`` are published in
:meth:`BisectionAdapter.roots_record`. A bound weighted zero is not searched:
its root would move nothing, and a missing sign change on it would refuse a
search that does not depend on it.

The budget is known before the first solve (:func:`root_search_budget`). With
``d`` the declared interval in decades, ``t = log10(1 + rel_tol)``, ``S`` sweep
points (two when ``sweep_points`` is zero), ``s = d / (S - 1)`` the sweep step,
``h(w) = ceil(log2(w / t))`` the halvings of a bracket ``w`` decades wide and
``E = bracket_expand``:

- one root inside the declared bounds costs ``N_nominal = S + h(s)``;
- one root found after ``e`` expansions costs ``S + 2e + h(1)``, since each
  expansion evaluates two new ends and leaves a bracket one decade wide;
- two roots inside the bounds cost ``S + 2 h(s) + 1``, the last one the solve
  at the combined value;
- two roots of which one needed ``e`` expansions cost
  ``S + 2e + h(1) + max(h(s), h(1)) + 1``;
- ``N_worst`` is the largest of those, reached at ``e = E`` whenever the sweep
  step is at most a decade.

On the Nancon, [1e-7, 1e-3] m/s, seven sweep points and one per cent: 15
evaluations inside the bounds, 17, 19, 21 and 23 after one to four expansions;
two roots cost 24 inside the bounds and 26 to 32 after expansions.
``max_iter = "auto"`` budgets the worst case; a declared budget below the
nominal case is refused before the first solve. When a budget still runs out,
the adapter publishes the halvings its brackets still need
(:attr:`BisectionAdapter.evaluations_remaining`), and the engine grants exactly
those, once.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
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

BOUNDS_COMPONENT = "n_bounds_scored"
"""The component saying how many bounds of a network output are in the cost."""

ROOT_BOUNDS: tuple[str, ...] = ("minimal", "maximal")
"""The bounds a two-root search closes one root on each, in this order."""

_DEFAULT_SIGNED_COMPONENT = "J_signed"

_SAME_POINT = 1e-12
"""Two points of the log variable this close are one point."""


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


def _check_roots(roots: int) -> int:
    """Return *roots* when the search can close that many, raise otherwise."""
    count = int(roots)
    if count not in (1, 2):
        raise OptimizerError(f"a root search closes one or two roots, got roots = {roots!r}.")
    return count


def _budget_in_log_space(
    width: float, tolerance: float, sweep_points: int, bracket_expand: int, roots: int = 1
) -> CountedBudget:
    """Count the evaluations for an interval *width* decades wide, per expansion."""
    points = _sweep_size(sweep_points)
    inside = _halvings(width / (points - 1), tolerance)
    after_one_decade = _halvings(1.0, tolerance)
    expansions = range(1, max(0, int(bracket_expand)) + 1)
    if roots == 1:
        nominal = points + inside
        expanded = [points + 2 * step + after_one_decade for step in expansions]
    else:
        # One more solve, at the combined value, once both brackets are closed.
        nominal = points + 2 * inside + 1
        expanded = [
            points + 2 * step + after_one_decade + max(inside, after_one_decade) + 1
            for step in expansions
        ]
    return CountedBudget(counts=(nominal, *expanded))


def root_search_budget(
    lower: float,
    upper: float,
    *,
    rel_tol: float = DEFAULT_REL_TOL,
    sweep_points: int = DEFAULT_SWEEP_POINTS,
    bracket_expand: int = DEFAULT_BRACKET_EXPAND,
    roots: int = 1,
) -> CountedBudget:
    """Return the evaluations the root search needs, per bracket expansion.

    ``lower`` and ``upper`` are the declared bounds in physical units. With ``d``
    the interval in decades, ``t = log10(1 + rel_tol)``, ``S`` the sweep points
    (two when zero), ``s = d / (S - 1)`` and ``h(w) = ceil(log2(w / t))``: one
    root costs ``S + h(s)`` inside the bounds and ``S + 2e + h(1)`` after ``e``
    expansions; two roots cost ``S + 2 h(s) + 1`` and
    ``S + 2e + h(1) + max(h(s), h(1)) + 1``, the last solve at the combined
    value. ``worst`` is the largest count. On the Nancon, [1e-7, 1e-3] with
    seven points and one per cent, one root counts 15, 17, 19, 21 and 23, two
    roots 24, 26, 28, 30 and 32.
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
        _check_roots(roots),
    )


def roots_scored(outputs: Iterable[Any]) -> int:
    """Return how many roots a root search on these network outputs closes: 1 or 2.

    Two when an output declares both an extent table and a minimal map, and
    weighs both bounds above zero: the criterion then publishes one residual
    per bound. One otherwise, which is the paper's search. Read off the
    declarations, before any solve, so the budget can count both roots.
    """
    for output in outputs:
        extent = getattr(output, "extent", None)
        if extent is None or not getattr(output, "has_minimal_map", False):
            continue
        weights = extent.weights
        if float(weights.minimal) > 0.0 and float(weights.maximal) > 0.0:
            return 2
    return 1


def _component(components: Mapping[str, float] | None, name: str) -> float | None:
    """Read one component, bare or ``<output>.<name>``; two outputs publishing it is an error."""
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
    return _component(components, name)


@dataclass(frozen=True)
class RootTarget:
    """One residual the search closes a bracket on.

    ``bound`` is ``None`` for the single root of the paper, else the bound of
    a network output scored on two (``"minimal"`` or ``"maximal"``).
    ``weight`` is that root's share of the returned value in log space.
    """

    component: str
    bound: str | None = None
    weight: float = 1.0

    @property
    def label(self) -> str:
        """How the root is named in a message."""
        return self.component if self.bound is None else f"{self.bound} bound ({self.component})"


@register_optimizer("bisection")
class BisectionAdapter:
    """Bracket the sign change of a residual, or of two, then close each bracket."""

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
        roots: int = 1,
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
        # A residual named by hand is one root, whatever the outputs score.
        self._declared_roots = (
            _check_roots(roots) if self._signed_component == _DEFAULT_SIGNED_COMPONENT else 1
        )
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
        self._residuals: dict[int, dict[str, float]] = {}
        self._points: dict[int, float] = {}
        self._pending: list[float] = self._initial_points()
        self._pending_kind = "sweep"
        self._expansions = 0
        self._targets: tuple[RootTarget, ...] | None = None
        self._brackets: dict[str, tuple[float, float]] = {}
        self._combined_trial: int | None = None
        self._done = False
        self._trial_id = 0

    # -- the residuals ------------------------------------------------------ #

    def _decide_targets(self, components: Mapping[str, float]) -> tuple[RootTarget, ...]:
        """Say which residuals the search closes, from the first trial that scored.

        A declared ``signed_component`` other than the default is taken as
        written. Otherwise an output scoring two bounds publishes one residual
        per bound and their weights; a bound weighted zero is dropped.
        """
        single = (RootTarget(self._signed_component),)
        if self._signed_component != _DEFAULT_SIGNED_COMPONENT:
            return single
        n_bounds = _component(components, BOUNDS_COMPONENT)
        if n_bounds is None or int(round(n_bounds)) < 2:
            return single
        targets: list[RootTarget] = []
        for bound in ROOT_BOUNDS:
            weight = _component(components, f"weight_{bound}")
            if weight is None:
                raise ObjectiveError(
                    f"the output scores two bounds and publishes no 'weight_{bound}', so the "
                    "two roots cannot be combined."
                )
            if weight > 0.0:
                targets.append(RootTarget(f"{_DEFAULT_SIGNED_COMPONENT}_{bound}", bound, weight))
        if not targets:
            raise ObjectiveError("the output weighs both of its bounds zero: nothing to search.")
        if len(targets) == 1:
            # The other bound moves nothing: one root, read on its own residual.
            return (RootTarget(targets[0].component, targets[0].bound, 1.0),)
        return tuple(targets)

    def _set_targets(self, targets: tuple[RootTarget, ...]) -> None:
        """Fix the residuals once, and say it when the budget counted another number."""
        self._targets = targets
        if len(targets) == 2:
            logger.info(
                "The outputs score two bounds: one root per bound, on %s, combined as "
                "log K = %.3g log K*_minimal + %.3g log K*_maximal.",
                " and ".join(target.component for target in targets),
                targets[0].weight,
                targets[1].weight,
            )
        if len(targets) != self._declared_roots:
            logger.warning(
                "The budget was counted for %d root(s) and the outputs score %d: the "
                "declarations the runner read did not name every bound. The search closes "
                "%d; max_iter may run short, and the engine grants what it still needs once.",
                self._declared_roots,
                len(targets),
                len(targets),
            )

    def _read_residuals(self, result: EvaluationResult) -> dict[str, float] | None:
        """Return every residual this trial publishes, None when one is missing."""
        if self._targets is None:
            return None
        found: dict[str, float] = {}
        for target in self._targets:
            value = signed_residual(result.components, name=target.component)
            if value is None:
                if result.status == "completed":
                    raise ObjectiveError(
                        f"trial {result.trial_id} published no {target.component!r} "
                        "component, so its sign is unknown and a root search is blind. "
                        "Declare a network output, whose criterion emits it."
                    )
                return None
            found[target.component] = float(value)
        return found

    def _evaluated(self, component: str) -> list[tuple[float, float]]:
        """Return ``(x, residual)`` for every usable evaluation, x ascending."""
        pairs = [
            (self._points[trial], residuals[component])
            for trial, residuals in self._residuals.items()
            if trial in self._points and math.isfinite(residuals[component])
        ]
        return sorted(pairs)

    # -- planning ----------------------------------------------------------- #

    def _initial_points(self) -> list[float]:
        """The first points to evaluate: a coarse sweep, or the two bounds."""
        if self._sweep_points <= 0:
            return [self._low, self._high]
        count = max(2, self._sweep_points)
        step = (self._high - self._low) / (count - 1)
        return [self._low + step * index for index in range(count)]

    def _find_bracket(self, target: RootTarget) -> tuple[float, float] | None:
        """Return the tightest pair of consecutive points that change sign."""
        pairs = self._evaluated(target.component)
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
                "The residual %s changes sign %d times over the sweep, so the root is not "
                "unique on this interval. The tightest crossing is the one closed; the "
                "sweep curve is worth reading before trusting the value.",
                target.component,
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
        self._pending_kind = "sweep"
        logger.info(
            "No sign change yet: widening the bracket to [%.3f, %.3f] in log space "
            "(expansion %d of %d).",
            self._low,
            self._high,
            self._expansions,
            self._max_expansions,
        )
        return True

    def _refuse(self, target: RootTarget | None) -> None:
        """Raise, naming both ends, rather than returning the better of the two."""
        pairs = self._evaluated(target.component) if target is not None else []
        if not pairs:
            raise OptimizerError(
                "the bisection adapter has no usable residual: every evaluation failed. "
                f"Check that the outputs publish a {self._signed_component!r} component."
            )
        (x_low, r_low), (x_high, r_high) = pairs[0], pairs[-1]
        name = self._parameter.name
        which = "" if target.bound is None else f" of the {target.bound} bound"
        raise OptimizerError(
            f"the residual{which} keeps the same sign over the whole bracket: "
            f"{target.component} = {r_low:+.4g} at {name} = "
            f"{self._parameter.to_physical(x_low):.4g}, and {r_high:+.4g} at {name} = "
            f"{self._parameter.to_physical(x_high):.4g}. There is no root to close here. "
            "Returning the better of the two ends would be a minimised mean distance in "
            "disguise, so the search stops instead."
        )

    def _plan_after_batch(self) -> None:
        """Decide what to evaluate next, once a batch has been told.

        The sweep, an expansion and the combined value are evaluated whole.
        Midpoints are recomputed after every batch: with two brackets, the
        midpoint of one may fall in the other and narrow it too.
        """
        if self._pending and self._pending_kind != "bisect":
            return
        self._pending = []
        if self._combined_trial is not None:
            # The combined value is the last solve; its residuals move no bracket.
            self._done = True
            return
        if self._targets is None:
            self._done = True
            self._refuse(None)
            return
        brackets = {target.component: self._find_bracket(target) for target in self._targets}
        missing = [target for target in self._targets if brackets[target.component] is None]
        if missing:
            if any(result.status != "completed" for result in self._history):
                # A failed end means the surface, not the interval: widening it
                # would only buy more failures.
                self._done = True
                self._refuse(missing[0])
            if not self._expand():
                self._done = True
                self._refuse(missing[0])
            return
        self._brackets = {key: value for key, value in brackets.items() if value is not None}
        middles: list[float] = []
        for low, high in self._brackets.values():
            middle = 0.5 * (low + high)
            if high - low > self._tolerance and not any(
                abs(middle - seen) <= _SAME_POINT for seen in middles
            ):
                middles.append(middle)
        if middles:
            self._pending = middles
            self._pending_kind = "bisect"
            return
        self._plan_the_combined_value()

    def _plan_the_combined_value(self) -> None:
        """Every bracket is closed: evaluate the combined value, or stop."""
        if len(self._targets or ()) < 2 or self._combined_trial is not None:
            self._done = True
            return
        stars = self._root_trials()
        if any(trial is None for trial in stars.values()):
            # No completed trial inside a bracket: nothing real to combine.
            self._done = True
            return
        combined = self._combined_point(stars)
        logger.info(
            "Both roots closed: %s. The returned value is their weighted geometric mean, "
            "%s = %.6g, evaluated once so every number beside it comes from a solve.",
            ", ".join(
                f"K*_{target.bound} = {self._physical_of(stars[target.component]):.6g}"
                for target in self._targets or ()
            ),
            self._parameter.name,
            self._parameter.to_physical(combined),
        )
        existing = next(
            (
                trial
                for trial, x in self._points.items()
                if abs(x - combined) <= _SAME_POINT and self._completed(trial)
            ),
            None,
        )
        if existing is not None:
            self._combined_trial = existing
            self._done = True
            return
        self._pending = [combined]
        self._pending_kind = "combined"

    # -- the ask / tell contract -------------------------------------------- #

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        """Return up to ``n`` points, or nothing when every bracket is closed."""
        if self._done:
            return []
        out: list[ParamSuggestion] = []
        while self._pending and len(out) < max(1, int(n)):
            x = self._pending.pop(0)
            self._trial_id += 1
            self._points[self._trial_id] = x
            if self._pending_kind == "combined":
                self._combined_trial = self._trial_id
                source = "combined"
            else:
                source = "bisect" if self._brackets else "sweep"
            out.append(
                ParamSuggestion(
                    trial_id=self._trial_id,
                    values={self._parameter.name: float(self._parameter.to_physical(x))},
                    source=source,
                )
            )
        return out

    def suggest_next(self) -> ParamSuggestion:
        points = self.ask(1)
        if not points:
            raise OptimizerError("the bisection adapter has nothing left to suggest.")
        return points[0]

    def tell(self, results: Sequence[EvaluationResult]) -> None:
        """Record the residuals of each evaluation, then plan the next batch."""
        for result in results:
            self._history.append(result)
            if self._targets is None and result.components:
                self._set_targets(self._decide_targets(result.components))
            if self._targets is None:
                if result.status == "completed":
                    raise ObjectiveError(
                        f"trial {result.trial_id} published no {self._signed_component!r} "
                        "component, so its sign is unknown and a root search is blind. "
                        "Declare a network output, whose criterion emits it."
                    )
                continue
            residuals = self._read_residuals(result)
            if residuals is not None:
                self._residuals[result.trial_id] = residuals
        self._plan_after_batch()

    # -- the answer --------------------------------------------------------- #

    def best(self) -> EvaluationResult | None:
        """Return the evaluated trial the search answers with.

        One root: the trial closest to the root, inside the bracket. The cost
        carries ``abs`` of the residual, so the lowest cost is the trial nearest
        zero. What is returned is a point that was really evaluated, never the
        middle of the last interval: every quantity the method publishes beside
        the value has to come from a real solve.

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

        Two roots: the trial at the combined value, once it solved. Before
        that, or when it failed, the search has not converged and the lowest
        cost stands in, as for any search stopped by its budget.
        """
        valid = [result for result in self._history if result.status == "completed"]
        if not valid:
            return None
        if len(self._targets or ()) == 2:
            winner = self._combined_result()
            if winner is None:
                winner = min(valid, key=lambda result: result.objective_value)
        else:
            winner = self._pick(valid)
        self._warn_if_outside_the_declared_bounds(winner)
        return winner

    def _single_bracket(self) -> tuple[float, float] | None:
        """The bracket of a one-root search, None before it is found or with two roots."""
        if self._targets is None or len(self._targets) != 1:
            return None
        return self._brackets.get(self._targets[0].component)

    def _pick(self, valid: list[EvaluationResult]) -> EvaluationResult:
        """Choose among completed trials, preferring those inside the bracket."""
        bracket = self._single_bracket()
        inside = [result for result in valid if self._inside(result.trial_id, bracket)]
        pool = inside or valid
        lowest = min(result.objective_value for result in pool)
        tied = [result for result in pool if _same_cost(result.objective_value, lowest)]
        if bracket is None:
            return tied[0]
        middle = 0.5 * (bracket[0] + bracket[1])
        winner = min(
            tied, key=lambda result: abs(self._points.get(result.trial_id, middle) - middle)
        )
        if not inside:
            low, high = bracket
            logger.warning(
                "No completed trial lies inside the final bracket [%.4g, %.4g] of %s: its "
                "ends come from rejected trials. Trial %d, outside it, is returned.",
                self._parameter.to_physical(low),
                self._parameter.to_physical(high),
                self._parameter.name,
                winner.trial_id,
            )
        return winner

    def _inside(self, trial_id: int, bracket: tuple[float, float] | None) -> bool:
        """Whether a trial was evaluated inside *bracket*, ends included."""
        if bracket is None:
            return False
        x = self._points.get(trial_id)
        if x is None:
            return False
        low, high = bracket
        slack = 1e-12 * max(1.0, abs(low), abs(high))
        return low - slack <= x <= high + slack

    def _completed(self, trial_id: int) -> bool:
        """Whether this trial solved."""
        return any(
            result.trial_id == trial_id and result.status == "completed" for result in self._history
        )

    def _root_trials(self) -> dict[str, int | None]:
        """Return, per residual, the completed trial nearest its root.

        Inside the bracket, the smallest residual in absolute value wins, and
        a tie goes to the trial nearest the middle of the bracket. None when
        no completed trial lies inside.
        """
        stars: dict[str, int | None] = {}
        for target in self._targets or ():
            bracket = self._brackets.get(target.component)
            if bracket is None:
                stars[target.component] = None
                continue
            candidates = [
                (abs(residuals[target.component]), trial)
                for trial, residuals in self._residuals.items()
                if self._completed(trial)
                and math.isfinite(residuals[target.component])
                and self._inside(trial, bracket)
            ]
            if not candidates:
                stars[target.component] = None
                continue
            lowest = min(value for value, _ in candidates)
            middle = 0.5 * (bracket[0] + bracket[1])
            stars[target.component] = min(
                (trial for value, trial in candidates if _same_cost(value, lowest)),
                key=lambda trial: abs(self._points[trial] - middle),
            )
        return stars

    def _combined_point(self, stars: Mapping[str, int | None]) -> float:
        """Return ``sum w x*`` over the roots, the weighted mean in log space."""
        targets = self._targets or ()
        total = sum(target.weight for target in targets)
        return sum(
            target.weight * self._points[int(stars[target.component])]  # type: ignore[arg-type]
            for target in targets
        ) / (total or 1.0)

    def _combined_result(self) -> EvaluationResult | None:
        """Return the completed trial at the combined value, None before or on failure."""
        if self._combined_trial is None:
            return None
        return next(
            (
                result
                for result in self._history
                if result.trial_id == self._combined_trial and result.status == "completed"
            ),
            None,
        )

    def _physical_of(self, trial_id: int | None) -> float:
        """Return a trial's parameter value in physical units, NaN when absent."""
        if trial_id is None or trial_id not in self._points:
            return float("nan")
        return float(self._parameter.to_physical(self._points[trial_id]))

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
        """Whether every bracket is closed, and with two roots the combined value solved.

        ``_done`` alone is not enough. A refusal also sets it before raising, with
        no bracket ever found, and a caller that catches that error must not read
        the search as converged.
        """
        if not self._done or self._targets is None:
            return False
        if any(target.component not in self._brackets for target in self._targets):
            return False
        if len(self._targets) == 2:
            return self._combined_result() is not None
        return True

    @property
    def counted_budget(self) -> CountedBudget:
        """Evaluations the declared bounds, sweep, tolerance and roots need, per expansion.

        Read by the engine before the first solve: ``"auto"`` budgets its worst
        case, a budget below its nominal case is refused. See
        :func:`root_search_budget`.
        """
        low, high = self._declared
        return _budget_in_log_space(
            high - low,
            self._tolerance,
            self._sweep_points,
            self._max_expansions,
            self._declared_roots,
        )

    @property
    def evaluations_remaining(self) -> int | None:
        """Evaluations the current brackets still need, or None before they are found.

        ``ceil(log2(width / t))`` per open bracket, plus the solve at the
        combined value with two roots; zero once the search is done. Before
        every sign change is found the sweep or an expansion is still running,
        and what follows it is not known yet.
        """
        if self._targets is None or any(
            target.component not in self._brackets for target in self._targets
        ):
            return None
        if self._done:
            return 0
        needed = sum(
            _halvings(high - low, self._tolerance) for low, high in self._brackets.values()
        )
        if len(self._targets) == 2 and self._combined_result() is None:
            needed += 1
        return needed

    @property
    def bracket(self) -> tuple[float, float] | None:
        """The latest bracket of a one-root search, in the transformed variable.

        Set as soon as a sign change is found and narrowed by each step;
        :meth:`converged` says whether it reached the tolerance. None with two
        roots, whose brackets are :attr:`brackets`.
        """
        return self._single_bracket()

    @property
    def brackets(self) -> dict[str, tuple[float, float]]:
        """The latest bracket per bound of a two-root search, in the transformed variable.

        Keyed ``"minimal"`` and ``"maximal"``; empty before both are found and
        for a one-root search.
        """
        if self._targets is None or len(self._targets) != 2:
            return {}
        return {
            str(target.bound): self._brackets[target.component]
            for target in self._targets
            if target.component in self._brackets
        }

    @property
    def roots(self) -> int:
        """The roots the search closes: those the outputs score, else those declared."""
        return len(self._targets) if self._targets is not None else self._declared_roots

    def _bracket_entry(self, bracket: tuple[float, float], *, closed: bool) -> dict[str, Any]:
        """Return one bracket in physical units, with its relative width."""
        low, high = bracket
        return {
            "low": float(self._parameter.to_physical(low)),
            "high": float(self._parameter.to_physical(high)),
            "relative_width": float(10.0 ** (high - low) - 1.0),
            "closed": closed,
        }

    def progress_label(self) -> str:
        """Return what the live progress line shows: the bracket, not a cost.

        A root search answers with a root. The lowest cost seen is often a trial
        far from it, so a progress line naming it contradicts the answer. The
        line names the bracket, or the brackets on two bounds, and once solved
        the combined value.
        """
        name = self._parameter.name
        combined = self._combined_result()
        if combined is not None:
            return f"root {name} = {self._physical_of(combined.trial_id):.4g}"
        if self._targets is None or not self._brackets:
            return f"bracketing {name}"
        parts = []
        for target in self._targets:
            bracket = self._brackets.get(target.component)
            if bracket is None:
                continue
            low, high = (float(self._parameter.to_physical(end)) for end in bracket)
            side = "" if target.bound is None else f"{target.bound} "
            parts.append(f"{side}root {name} in [{low:.4g}, {high:.4g}]")
        return ", ".join(parts) if parts else f"bracketing {name}"

    def bracket_record(self) -> dict[str, Any] | None:
        """Return the final bracket for the report, or None before a sign change.

        ``low`` and ``high`` are in the parameter's physical units and
        ``relative_width`` is ``high / low - 1``, the number ``rel_tol`` is read
        against. ``closed`` is False when the budget ran out first: the root is
        still inside, only less precisely than asked. The paper publishes no
        such interval; it is what the search itself proved, which the tolerance
        interval on the trials does not. None for a two-root search, whose
        record is :meth:`roots_record`.
        """
        bracket = self._single_bracket()
        if bracket is None:
            return None
        return {
            "parameter": self._parameter.name,
            **self._bracket_entry(bracket, closed=self.converged()),
        }

    def roots_record(self) -> dict[str, Any] | None:
        """Return the two roots, their spread and the combined value, or None.

        None unless the search closes two roots and found both sign changes.
        Per bound: ``k_star``, the completed trial nearest its root
        (``trial_id``, ``residual`` there), its final bracket in physical
        units and whether it closed, and its ``weight``. Then
        ``delta_log10 = log10(K*_maximal / K*_minimal)``, the combined
        ``value`` and ``combined_trial_id``, the trial that solved it, None
        when it did not. ``closed`` is :meth:`converged`.
        """
        if self._targets is None or len(self._targets) != 2:
            return None
        if any(target.component not in self._brackets for target in self._targets):
            return None
        stars = self._root_trials()
        record: dict[str, Any] = {"parameter": self._parameter.name}
        for target in self._targets:
            bracket = self._brackets[target.component]
            trial = stars[target.component]
            residual = (
                self._residuals.get(trial, {}).get(target.component) if trial is not None else None
            )
            record[str(target.bound)] = {
                "k_star": self._physical_of(trial),
                "trial_id": trial,
                "residual": float(residual) if residual is not None else None,
                "weight": float(target.weight),
                **self._bracket_entry(bracket, closed=bracket[1] - bracket[0] <= self._tolerance),
            }
        k_min = record["minimal"]["k_star"]
        k_max = record["maximal"]["k_star"]
        record["delta_log10"] = (
            float(math.log10(k_max / k_min))
            if math.isfinite(k_min) and math.isfinite(k_max) and k_min > 0.0 and k_max > 0.0
            else None
        )
        combined = self._combined_result()
        record["value"] = self._physical_of(combined.trial_id) if combined is not None else None
        record["combined_trial_id"] = combined.trial_id if combined is not None else None
        record["closed"] = self.converged()
        return record


__all__ = [
    "BOUNDS_COMPONENT",
    "DEFAULT_BRACKET_EXPAND",
    "DEFAULT_REL_TOL",
    "DEFAULT_SWEEP_POINTS",
    "LOG10_ONE_PERCENT",
    "ROOT_BOUNDS",
    "BisectionAdapter",
    "RootTarget",
    "root_search_budget",
    "roots_scored",
    "signed_residual",
]
