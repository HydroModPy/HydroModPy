"""One-dimensional root search on the sign of a residual, as one flat module.

Same optimizer as ``hydromodpy.calibration.optim.adapters.bisection_adapter``,
written on the public ask/tell/best contract. It does the whole job: a coarse
log sweep, bracket expansion by decades, one or two roots (one per bound of a
network output) with a weighted geometric mean solved once, ``n`` cut points
per ask, the counted budget, the evaluations still needed, the records for the
report and the interval around the root.

The stopping rule is the width of the bracket, never the size of the residual,
because the residual steps over zero. A bracket that never changes sign is
refused, never answered with the better end.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from hydromodpy.calibration.optim.cost_margin import ParameterInterval, root_interval
from hydromodpy.calibration.optim.method_config import BisectionMethodConfig
from hydromodpy.calibration.optim.optimizer import (
    EngineTraits,
    EvaluationResult,
    ParamSuggestion,
)
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.calibration.optim.stopping import CountedBudget
from hydromodpy.core.exceptions import ObjectiveError, OptimizerError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.scoring.cost_margin import MarginKind

logger = get_logger(__name__)

LOG10_ONE_PERCENT = 4.32137e-3
DEFAULT_REL_TOL = 0.01
DEFAULT_SWEEP_POINTS = 7
DEFAULT_BRACKET_EXPAND = 4
BOUNDS_COMPONENT = "n_bounds_scored"
ROOT_BOUNDS = ("minimal", "maximal")
_SIGNED = "J_signed"
_EPS = 1e-12


def _same(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=_EPS)


def _at_least(value: int, low: int, what: str) -> int:
    if int(value) < low:
        raise OptimizerError(what.format(value))
    return int(value)


def _check_batch(batch: int) -> int:
    return _at_least(batch, 1, "a root search asks at least one point at a time, got {!r}.")


def _check_roots(roots: int) -> int:
    if int(roots) not in (1, 2):
        raise OptimizerError(f"a root search closes one or two roots, got roots = {roots!r}.")
    return int(roots)


# -- the count of evaluations, known before the first solve --------------------------------- #
def _share(widths: Sequence[float], tol: float, points: int) -> list[int]:
    """Share one round of cut points: one each first, then to the bracket left widest."""
    needs = [0 if w <= tol else max(1, math.ceil(w / tol) - 1) for w in widths]
    shares, left = [0] * len(needs), max(0, int(points))
    for i, need in enumerate(needs):
        if left and need:
            shares[i], left = 1, left - 1
    while left:
        wanting = [i for i, need in enumerate(needs) if shares[i] < need]
        if not wanting:
            break
        shares[max(wanting, key=lambda i: widths[i] / (shares[i] + 1))] += 1
        left -= 1
    return shares


def _cut_evaluations(widths: Sequence[float], tol: float, batch: int) -> int:
    """Evaluations that close brackets *widths* wide, *batch* cuts per round."""
    current, spent = [float(w) for w in widths], 0
    while any(shares := _share(current, tol, batch)):
        current = [w / (s + 1) for w, s in zip(current, shares, strict=True)]
        spent += sum(shares)
    return spent


def _budget(width: float, tol: float, sweep: int, expand: int, roots: int, batch: int):
    n = 2 if sweep <= 0 else max(2, int(sweep))
    step = width / (n - 1)
    cut = lambda *w: _cut_evaluations(w, tol, batch)  # noqa: E731
    steps = range(1, max(0, int(expand)) + 1)
    if roots == 1:
        return CountedBudget((n + cut(step), *(n + 2 * e + cut(1.0) for e in steps)))
    after = cut(1.0, max(step, 1.0))
    return CountedBudget((n + cut(step, step) + 1, *(n + 2 * e + after + 1 for e in steps)))


def root_search_budget(
    lower: float,
    upper: float,
    *,
    rel_tol: float = DEFAULT_REL_TOL,
    sweep_points: int = DEFAULT_SWEEP_POINTS,
    bracket_expand: int = DEFAULT_BRACKET_EXPAND,
    roots: int = 1,
    batch: int = 1,
) -> CountedBudget:
    """Evaluations per bracket expansion, for bounds in physical units."""
    if not 0.0 < float(lower) < float(upper):
        raise ValueError(
            f"a root search on a log parameter needs 0 < lower < upper, got [{lower}, {upper}]."
        )
    if float(rel_tol) <= 0.0:
        raise ValueError(f"rel_tol must be strictly positive, got {rel_tol}.")
    return _budget(
        math.log10(upper) - math.log10(lower),
        math.log10(1.0 + float(rel_tol)),
        int(sweep_points),
        int(bracket_expand),
        _check_roots(roots),
        _check_batch(batch),
    )


# -- reading the residuals ------------------------------------------------------------------ #
def _component(components: Mapping[str, float] | None, name: str) -> float | None:
    """Read a component, bare or ``<output>.<name>``; two outputs publishing it is an error."""
    if not components:
        return None
    if name in components:
        return float(components[name])
    found = [key for key in components if key.endswith(f".{name}")]
    if len(found) > 1:
        raise OptimizerError(
            f"several outputs publish a {name!r} residual ({sorted(found)}); a root "
            "search needs exactly one."
        )
    return float(components[found[0]]) if found else None


def signed_residual(components: Mapping[str, float] | None, *, name: str = _SIGNED):
    """Read the signed residual of a trial, None when absent."""
    return _component(components, name)


def roots_scored(outputs: Iterable[Any]) -> int:
    """Roots a search closes on these outputs: two when one scores both bounds, else one."""
    for out in outputs:
        if out.model.extent is None or out.map.permanent is None:
            continue
        w = out.map.bound_weights
        if float(w.permanent) > 0.0 and float(w.complete) > 0.0:
            return 2
    return 1


@dataclass(frozen=True)
class RootTarget:
    """One residual a bracket is closed on. ``bound`` is None for the single root."""

    component: str
    bound: str | None = None
    weight: float = 1.0

    @property
    def label(self) -> str:
        return self.component if self.bound is None else f"{self.bound} bound ({self.component})"


class BisectionAdapter:
    """Bracket the sign change of a residual (or two), then close each bracket."""

    name = "bisection"
    options = BisectionMethodConfig
    traits = EngineTraits(
        max_parameters=1,
        required_search_space="log",
        needs_signed_residual=True,
        supports_parallel=True,
        restarts_explore_differently=False,
        precision_option="rel_tol",
        precision_reads="relative_value",
    )

    def __init__(
        self,
        space: ParameterSpace,
        *,
        seed: int | None = None,
        rel_tol: float = DEFAULT_REL_TOL,
        signed_component: str = _SIGNED,
        sweep_points: int = DEFAULT_SWEEP_POINTS,
        bracket_expand: int = DEFAULT_BRACKET_EXPAND,
        roots: int = 1,
        batch: int = 1,
    ) -> None:
        del seed  # deterministic
        if space.dim != 1:
            raise OptimizerError(
                "the bisection adapter searches one parameter; the space declares "
                f"{space.dim} ({', '.join(space.names)}). A two-parameter space silently "
                "bisected along its first axis is the worst failure this method has."
            )
        p = space.parameters[0]
        if p.search_space != "log":
            raise OptimizerError(
                f"the bisection adapter walks a log10 variable, but parameter {p.name!r} "
                f"declares search_space = {p.search_space!r}. Its stopping rule is a width in "
                "that variable, so on any other search space it reads as an absolute width "
                "and reports convergence on a bracket orders of magnitude wide. "
                'Declare search_space = "log" for this parameter.'
            )
        if float(rel_tol) <= 0.0:
            raise OptimizerError(f"rel_tol must be strictly positive, got {rel_tol}.")
        _at_least(sweep_points, 0, "sweep_points must be positive or zero, got {}.")
        self.space, self._parameter = space, p
        self._signed_component = str(signed_component)
        self._sweep_points = int(sweep_points)
        self._max_expansions = max(0, int(bracket_expand))
        by_hand = self._signed_component != _SIGNED  # a residual named by hand is one root
        self._declared_roots = 1 if by_hand else _check_roots(roots)
        self._batch, self._widest = _check_batch(batch), None
        self._tolerance = math.log10(1.0 + float(rel_tol))
        self._declared = (float(p.lower_transformed), float(p.upper_transformed))
        self._low, self._high = self._declared
        self._history: list[EvaluationResult] = []
        self._residuals: dict[int, dict[str, float]] = {}
        self._points: dict[int, float] = {}
        self._ok: set[int] = set()
        n = max(2, self._sweep_points) if self._sweep_points > 0 else 2
        step = (self._high - self._low) / (n - 1)
        self._pending = (
            [self._low + step * i for i in range(n)]
            if self._sweep_points > 0
            else [self._low, self._high]
        )
        self._kind = "sweep"
        self._expansions, self._trial_id = 0, 0
        self._targets: tuple[RootTarget, ...] | None = None
        self._brackets: dict[str, tuple[float, float]] = {}
        self._combined_trial: int | None = None
        self._round_due = self._done = False

    # -- targets and residuals ------------------------------------------------------------- #
    def _decide_targets(self, components: Mapping[str, float]) -> tuple[RootTarget, ...]:
        single = (RootTarget(self._signed_component),)
        n_bounds = _component(components, BOUNDS_COMPONENT)
        if self._signed_component != _SIGNED or n_bounds is None or round(n_bounds) < 2:
            return single
        targets = []
        for bound in ROOT_BOUNDS:
            weight = _component(components, f"weight_{bound}")
            if weight is None:
                raise ObjectiveError(
                    f"the output scores two bounds and publishes no 'weight_{bound}', so the "
                    "two roots cannot be combined."
                )
            if weight > 0.0:
                targets.append(RootTarget(f"{_SIGNED}_{bound}", bound, weight))
        if not targets:
            raise ObjectiveError("the output weighs both of its bounds zero: nothing to search.")
        if len(targets) == 1:  # the other bound moves nothing
            return (RootTarget(targets[0].component, targets[0].bound, 1.0),)
        return tuple(targets)

    def _set_targets(self, targets: tuple[RootTarget, ...]) -> None:
        self._targets = targets
        if len(targets) == 2:
            logger.info(
                "The outputs score two bounds: one root per bound, on %s and %s, combined as "
                "log K = %.3g log K*_minimal + %.3g log K*_maximal.",
                targets[0].component,
                targets[1].component,
                targets[0].weight,
                targets[1].weight,
            )
        if len(targets) != self._declared_roots:
            logger.warning(
                "The budget was counted for %d root(s) and the outputs score %d: the "
                "declarations the runner read did not name every bound. The search closes "
                "%d; max_trials may run short, and the engine grants what it still needs once.",
                self._declared_roots,
                len(targets),
                len(targets),
            )

    def _evaluated(self, component: str) -> list[tuple[float, float]]:
        """``(x, residual)`` of every usable evaluation, x ascending."""
        return sorted(
            (self._points[t], r[component])
            for t, r in self._residuals.items()
            if t in self._points and math.isfinite(r[component])
        )

    # -- planning --------------------------------------------------------------------------- #
    def _find_bracket(self, target: RootTarget) -> tuple[float, float] | None:
        """Tightest pair of consecutive points that change sign."""
        pairs = self._evaluated(target.component)
        found = []
        for (xl, rl), (xh, rh) in zip(pairs[:-1], pairs[1:], strict=False):
            if rl == 0.0:
                return (xl, xl)
            if rl * rh < 0.0:
                found.append((xl, xh))
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
        tightest = min(found, key=lambda pair: pair[1] - pair[0])
        return self._as_bisection_keeps(pairs, found, tightest, target)

    def _as_bisection_keeps(self, pairs, found, tightest, target):
        """Among crossings of one width in the last bracket, keep the one binary bisection keeps.

        The halvings are followed through the points evaluated while each midpoint is one of
        them. Past the last one, the lowest crossing left is kept.
        """
        previous = self._brackets.get(target.component)
        if previous is None:
            return tightest
        low, high = previous
        span = tightest[1] - tightest[0]
        tied = [
            c
            for c in found
            if math.isclose(c[1] - c[0], span, rel_tol=1e-9, abs_tol=_EPS)
            and c[0] >= low - _EPS
            and c[1] <= high + _EPS
        ]
        if len(tied) < 2:
            return tightest
        near = lambda x: next((r for p, r in pairs if abs(p - x) <= _EPS), None)  # noqa: E731
        while len(tied) > 1:
            middle = 0.5 * (low + high)
            at_low, at_mid = near(low), near(middle)
            if at_low is None or at_mid is None or at_mid == 0.0:
                break
            low, high = (low, middle) if at_low * at_mid < 0.0 else (middle, high)
            kept = [c for c in tied if c[0] >= low - _EPS and c[1] <= high + _EPS]
            if not kept:
                break
            tied = kept
        return tied[0]

    def _expand(self) -> bool:
        """Widen the interval by one decade on both sides. False when exhausted."""
        if self._expansions >= self._max_expansions:
            return False
        self._expansions += 1
        self._low, self._high = self._low - 1.0, self._high + 1.0
        self._pending, self._kind = [self._low, self._high], "sweep"
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
        """Raise naming both ends, never returning the better of the two."""
        pairs = self._evaluated(target.component) if target is not None else []
        if not pairs:
            raise OptimizerError(
                "the bisection adapter has no usable residual: every evaluation failed or "
                f"was infeasible. Check that the outputs publish a {self._signed_component!r} "
                "component."
            )
        (xl, rl), (xh, rh) = pairs[0], pairs[-1]
        name, p = self._parameter.name, self._parameter
        unsolved = ", ".join(
            f"{name} = {self._physical_of(r.trial_id):.4g} ({r.status})"
            for r in self._history
            if r.status != "completed"
        )
        infeasible = (
            f" It does not widen: a bracket end is infeasible, {unsolved}." if unsolved else ""
        )
        which = "" if target.bound is None else f" of the {target.bound} bound"
        raise OptimizerError(
            f"the residual{which} keeps the same sign over the whole bracket: "
            f"{target.component} = {rl:+.4g} at {name} = {p.to_physical(xl):.4g}, and "
            f"{rh:+.4g} at {name} = {p.to_physical(xh):.4g}. There is no root to close here. "
            "Returning the better of the two ends would be a minimised mean distance in "
            f"disguise, so the search stops instead.{infeasible}"
        )

    def _plan_after_batch(self) -> None:
        """Decide what to evaluate next, once a batch has been told."""
        if self._pending and self._kind != "bisect":
            return
        self._pending, self._round_due = [], False
        if self._combined_trial is not None:  # the combined solve is the last one
            self._done = True
            return
        if self._targets is None:
            self._done = True
            self._refuse(None)
        found = {t.component: self._find_bracket(t) for t in self._targets}
        missing = [t for t in self._targets if found[t.component] is None]
        if missing:
            # A failed end means the surface, not the interval: widening buys more failures.
            if any(r.status != "completed" for r in self._history) or not self._expand():
                self._done = True
                self._refuse(missing[0])
            return
        self._brackets = found
        if self._open_spans():
            self._kind, self._round_due = "bisect", True
        else:
            self._plan_the_combined_value()

    def _open_spans(self) -> list[tuple[float, float]]:
        """Brackets still wider than the tolerance, a bracket both roots share once."""
        spans: list[tuple[float, float]] = []
        for low, high in self._brackets.values():
            if high - low > self._tolerance and not any(
                abs(low - a) <= _EPS and abs(high - b) <= _EPS for a, b in spans
            ):
                spans.append((low, high))
        return spans

    def _cuts(self, points: int) -> list[float]:
        """Place one round of at most *points* cuts, as equal parts in the log variable."""
        spans = self._open_spans()
        shares = _share([high - low for low, high in spans], self._tolerance, points)
        placed: list[float] = []
        for (low, high), share in zip(spans, shares, strict=True):
            for i in range(1, share + 1):
                x = ((share + 1 - i) * low + i * high) / (share + 1)
                if not any(abs(x - seen) <= _EPS for seen in placed):
                    placed.append(x)
        return placed

    def _plan_the_combined_value(self) -> None:
        """Every bracket is closed: solve the weighted mean of the roots, or stop."""
        if len(self._targets or ()) < 2 or self._combined_trial is not None:
            self._done = True
            return
        stars = self._root_trials()
        if any(t is None for t in stars.values()):
            self._done = True  # no completed trial inside a bracket: nothing real to combine
            return
        total = sum(t.weight for t in self._targets) or 1.0
        combined = sum(t.weight * self._points[stars[t.component]] for t in self._targets) / total
        logger.info(
            "Both roots closed: %s. The returned value is their weighted geometric mean, "
            "%s = %.6g, evaluated once so every number beside it comes from a solve.",
            ", ".join(
                f"K*_{t.bound} = {self._physical_of(stars[t.component]):.6g}" for t in self._targets
            ),
            self._parameter.name,
            self._parameter.to_physical(combined),
        )
        existing = next(
            (t for t, x in self._points.items() if abs(x - combined) <= _EPS and t in self._ok),
            None,
        )
        if existing is not None:
            self._combined_trial, self._done = existing, True
            return
        self._pending, self._kind = [combined], "combined"

    # -- ask / tell ------------------------------------------------------------------------- #
    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        """Up to *n* points, or nothing when every bracket is closed."""
        if self._done:
            return []
        n = max(1, int(n))
        self._widest = max(self._widest or 0, n)
        if self._round_due:
            self._round_due, self._pending = False, self._cuts(n)
        out = []
        while self._pending and len(out) < n:
            x = self._pending.pop(0)
            self._trial_id += 1
            self._points[self._trial_id] = x
            if self._kind == "combined":
                self._combined_trial, source = self._trial_id, "combined"
            else:
                source = "bisect" if self._brackets else "sweep"
            values = {self._parameter.name: float(self._parameter.to_physical(x))}
            out.append(ParamSuggestion(trial_id=self._trial_id, values=values, source=source))
        return out

    def suggest_next(self) -> ParamSuggestion:
        points = self.ask(1)
        if not points:
            raise OptimizerError("the bisection adapter has nothing left to suggest.")
        return points[0]

    def tell(self, results: Sequence[EvaluationResult]) -> None:
        """Record the residuals of each evaluation, then plan the next batch."""
        for r in results:
            self._history.append(r)
            if r.status == "completed":
                self._ok.add(r.trial_id)
            if self._targets is None and r.components:
                self._set_targets(self._decide_targets(r.components))
            names = (
                [t.component for t in self._targets] if self._targets else [self._signed_component]
            )
            values = [signed_residual(r.components, name=c) for c in names]
            if None in values:
                if r.status == "completed":
                    raise ObjectiveError(
                        f"trial {r.trial_id} published no {names[values.index(None)]!r} "
                        "component, so its sign is unknown and a root search is blind. "
                        "Declare a network output, whose criterion emits it."
                    )
            elif self._targets is not None:
                self._residuals[r.trial_id] = dict(zip(names, map(float, values), strict=True))
        self._plan_after_batch()

    # -- the answer ------------------------------------------------------------------------- #
    def best(self) -> EvaluationResult | None:
        """The evaluated trial the search answers with, never a midpoint.

        One root: inside the bracket, the lowest cost, a tie going to the trial nearest the
        middle. Two roots: the trial at the combined value, else the lowest cost.
        """
        valid = [r for r in self._history if r.status == "completed"]
        if not valid:
            return None
        if len(self._targets or ()) == 2:
            winner = self._combined_result() or min(valid, key=lambda r: r.cost)
        else:
            winner = self._pick(valid)
        self._warn_if_outside_the_declared_bounds()
        return winner

    def _pick(self, valid: list[EvaluationResult]) -> EvaluationResult:
        bracket = self.bracket
        inside = [r for r in valid if self._inside(r.trial_id, bracket)]
        pool = inside or valid
        lowest = min(r.cost for r in pool)
        tied = [r for r in pool if _same(r.cost, lowest)]
        if bracket is None:
            return tied[0]
        middle = 0.5 * (bracket[0] + bracket[1])
        winner = min(tied, key=lambda r: abs(self._points.get(r.trial_id, middle) - middle))
        if not inside:
            logger.warning(
                "No completed trial lies inside the final bracket [%.4g, %.4g] of %s: its "
                "ends come from rejected trials. Trial %d, outside it, is returned.",
                self._parameter.to_physical(bracket[0]),
                self._parameter.to_physical(bracket[1]),
                self._parameter.name,
                winner.trial_id,
            )
        return winner

    def _inside(self, trial_id: int, bracket: tuple[float, float] | None) -> bool:
        x = self._points.get(trial_id)
        if bracket is None or x is None:
            return False
        slack = 1e-12 * max(1.0, abs(bracket[0]), abs(bracket[1]))
        return bracket[0] - slack <= x <= bracket[1] + slack

    def _root_trials(self) -> dict[str, int | None]:
        """Per residual, the completed trial nearest its root inside its bracket."""
        stars: dict[str, int | None] = {}
        for t in self._targets or ():
            bracket = self._brackets.get(t.component)
            cands = [
                (abs(r[t.component]), trial)
                for trial, r in self._residuals.items()
                if trial in self._ok
                and math.isfinite(r[t.component])
                and self._inside(trial, bracket)
            ]
            if bracket is None or not cands:
                stars[t.component] = None
                continue
            lowest, middle = min(v for v, _ in cands), 0.5 * (bracket[0] + bracket[1])
            stars[t.component] = min(
                (trial for v, trial in cands if _same(v, lowest)),
                key=lambda trial: abs(self._points[trial] - middle),
            )
        return stars

    def _combined_result(self) -> EvaluationResult | None:
        if self._combined_trial is None:
            return None
        return next(
            (
                r
                for r in self._history
                if r.trial_id == self._combined_trial and r.status == "completed"
            ),
            None,
        )

    def _physical_of(self, trial_id: int | None) -> float:
        if trial_id is None or trial_id not in self._points:
            return float("nan")
        return float(self._parameter.to_physical(self._points[trial_id]))

    def root_outside_bounds(self) -> str | None:
        """Name the roots whose bracket lies outside the declared bounds, or None."""
        low, high = self._declared
        phys = self._parameter.to_physical
        outside = []
        for t in self._targets or ():
            b = self._brackets.get(t.component)
            mid = None if b is None else 0.5 * (b[0] + b[1])
            if mid is not None and not low <= mid <= high:
                outside.append(f"the root of {t.label} at {phys(mid):.4g}")
        if not outside:
            return None
        return (
            f"{' and '.join(outside)} closed OUTSIDE the declared bounds of "
            f"{self._parameter.name}, [{phys(low):.4g}, {phys(high):.4g}], "
            f"after {self._expansions} bracket expansion(s)"
        )

    def _warn_if_outside_the_declared_bounds(self) -> None:
        reason = self.root_outside_bounds()
        if reason:
            logger.warning(
                "%s. Either the prior was too narrow, or the residual does not respond to "
                "this parameter over the declared range: a simulated network holding cells "
                "that are prescribed rather than computed never retracts, and the search then "
                "balances against that fixed skeleton. Check n_excess at the low end of the "
                "sweep: it should collapse as the parameter rises.",
                reason,
            )

    def converged(self) -> bool:
        """Every bracket closed, and with two roots the combined value solved."""
        if not self._done or self._targets is None:
            return False
        if any(t.component not in self._brackets for t in self._targets):
            return False
        return len(self._targets) < 2 or self._combined_result() is not None

    # -- budget and progress ---------------------------------------------------------------- #
    @property
    def _points_per_round(self) -> int:
        return self._widest if self._widest is not None else self._batch

    @property
    def counted_budget(self) -> CountedBudget:
        """Evaluations the bounds, sweep, tolerance and roots need, per expansion."""
        low, high = self._declared
        return _budget(
            high - low,
            self._tolerance,
            self._sweep_points,
            self._max_expansions,
            self._declared_roots,
            self._points_per_round,
        )

    @property
    def evaluations_remaining(self) -> int | None:
        """Evaluations the open brackets still need, None before every sign change is found."""
        if self._targets is None or any(t.component not in self._brackets for t in self._targets):
            return None
        if self._done:
            return 0
        widths = [high - low for low, high in self._open_spans()]
        needed = _cut_evaluations(widths, self._tolerance, self._points_per_round)
        return needed + (1 if len(self._targets) == 2 and self._combined_result() is None else 0)

    @property
    def bracket(self) -> tuple[float, float] | None:
        """The latest bracket of a one-root search, in the transformed variable."""
        if self._targets is None or len(self._targets) != 1:
            return None
        return self._brackets.get(self._targets[0].component)

    @property
    def brackets(self) -> dict[str, tuple[float, float]]:
        """The latest bracket per bound of a two-root search."""
        if self._targets is None or len(self._targets) != 2:
            return {}
        return {
            str(t.bound): self._brackets[t.component]
            for t in self._targets
            if t.component in self._brackets
        }

    @property
    def roots(self) -> int:
        return len(self._targets) if self._targets is not None else self._declared_roots

    def progress_label(self) -> str:
        """What the live progress line shows: the bracket, not a cost."""
        name = self._parameter.name
        combined = self._combined_result()
        if combined is not None:
            return f"root {name} = {self._physical_of(combined.trial_id):.4g}"
        parts = []
        for t in self._targets or ():
            if t.component in self._brackets:
                lo, hi = (
                    float(self._parameter.to_physical(e)) for e in self._brackets[t.component]
                )
                side = "" if t.bound is None else f"{t.bound} "
                parts.append(f"{side}root {name} in [{lo:.4g}, {hi:.4g}]")
        return ", ".join(parts) if parts else f"bracketing {name}"

    # -- records ---------------------------------------------------------------------------- #
    def _entry(self, bracket: tuple[float, float], *, closed: bool) -> dict[str, Any]:
        low, high = bracket
        return {
            "low": float(self._parameter.to_physical(low)),
            "high": float(self._parameter.to_physical(high)),
            "relative_width": float(10.0 ** (high - low) - 1.0),
            "closed": closed,
        }

    def bracket_record(self) -> dict[str, Any] | None:
        """The final bracket of a one-root search for the report, None before a sign change."""
        if self.bracket is None:
            return None
        return {
            "parameter": self._parameter.name,
            **self._entry(self.bracket, closed=self.converged()),
        }

    def root_interval(self, *, margin: float, kind: MarginKind) -> ParameterInterval | None:
        """Width of the answer on the cost curve, None before a trial solved."""
        best = self.best()
        if best is None:
            return None
        curve: dict[float, float | None] = {}
        for r in self._history:
            if r.trial_id not in self._points:
                continue
            solved = r.status == "completed" and math.isfinite(r.cost)
            x = self._points[r.trial_id]
            if curve.get(x) is None:
                curve[x] = r.cost if solved else None
        root = (self._points[best.trial_id], best.cost)
        return root_interval(curve, root, margin, kind, self._parameter, self._declared)

    def roots_record(self) -> dict[str, Any] | None:
        """Both roots, their spread and the combined value, None unless two roots were found."""
        if self._targets is None or len(self._targets) != 2:
            return None
        if any(t.component not in self._brackets for t in self._targets):
            return None
        stars = self._root_trials()
        record: dict[str, Any] = {"parameter": self._parameter.name}
        for t in self._targets:
            trial, b = stars[t.component], self._brackets[t.component]
            residual = (
                self._residuals.get(trial, {}).get(t.component) if trial is not None else None
            )
            record[str(t.bound)] = {
                "k_star": self._physical_of(trial),
                "trial_id": trial,
                "residual": float(residual) if residual is not None else None,
                "weight": float(t.weight),
                **self._entry(b, closed=b[1] - b[0] <= self._tolerance),
            }
        lo, hi = record["minimal"]["k_star"], record["maximal"]["k_star"]
        ok = math.isfinite(lo) and math.isfinite(hi) and lo > 0.0 and hi > 0.0
        record["delta_log10"] = float(math.log10(hi / lo)) if ok else None
        combined = self._combined_result()
        record["value"] = self._physical_of(combined.trial_id) if combined else None
        record["combined_trial_id"] = combined.trial_id if combined else None
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
