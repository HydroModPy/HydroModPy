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
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    register_optimizer,
)
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.core.exceptions import ObjectiveError, OptimizerError
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

LOG10_ONE_PERCENT = 4.32137e-3
"""``log10(1.01)``: the paper's "K/R varies by less than one per cent", written
in the log variable the search actually walks."""

_DEFAULT_SIGNED_COMPONENT = "J_signed"


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

    def __init__(
        self,
        space: ParameterSpace,
        *,
        seed: int | None = None,
        rel_tol: float = 0.01,
        signed_component: str = _DEFAULT_SIGNED_COMPONENT,
        sweep_points: int = 7,
        bracket_expand: int = 4,
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
        """Return the evaluated trial closest to the root.

        The cost carries ``abs`` of the residual, so the lowest cost is the
        trial nearest zero. What is returned is a point that was really
        evaluated, never the middle of the last interval: every quantity the
        method publishes beside the value has to come from a real solve.
        """
        valid = [result for result in self._history if result.status == "completed"]
        if not valid:
            return None
        winner = min(valid, key=lambda result: result.objective_value)
        self._warn_if_outside_the_declared_bounds(winner)
        return winner

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
        return self._done

    @property
    def bracket(self) -> tuple[float, float] | None:
        """The closed bracket in the transformed variable, once it is closed."""
        return self._bracket


__all__ = ["BisectionAdapter", "LOG10_ONE_PERCENT", "signed_residual"]
