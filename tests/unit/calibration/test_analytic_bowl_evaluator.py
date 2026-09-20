"""The surface a rehearsal is scored against, and what it refuses to invent.

The conformance suite holds this evaluator to the port, alongside every other
evaluator the installation serves. What it cannot hold it to is what it
computes, because that is this evaluator's own business: that the optimum sits
where the docstring says it sits, that a log-scaled parameter is positioned
geometrically, and that an unscorable sample comes back carrying ``nan``. A user
who names ``analytic_bowl`` to rehearse a montage reads the search against a
known answer, so the answer has to be the one that was promised.
"""

from __future__ import annotations

import math

import pytest

from hydromodpy.calibration.evaluation.analytic_bowl import BOWL_OPTIMUM, AnalyticBowlEvaluator
from hydromodpy.calibration.evaluation.port import TrialRequest
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace

pytestmark = pytest.mark.fast


def _space(*parameters: CalibParameter) -> ParameterSpace:
    return ParameterSpace(parameters)


LOG_K = CalibParameter(name="k", lower=1e-6, upper=1e-2, transform="log")
POROSITY = CalibParameter(name="porosity", lower=0.1, upper=0.3)


def _bowl(*parameters: CalibParameter) -> AnalyticBowlEvaluator:
    return AnalyticBowlEvaluator(space=_space(*parameters))


def _ask(bowl: AnalyticBowlEvaluator, values: dict[str, float]):
    return bowl.evaluate(TrialRequest(trial_id=1, values=values))


def _optimum(*parameters: CalibParameter) -> dict[str, float]:
    """The sample the bowl calls its minimum, read off the bounds.

    Read rather than written as a literal: ``0.2`` and the midpoint of
    ``[0.1, 0.3]`` are two different binary numbers, and a user rehearsing a
    montage gets the optimum from the interval the same way.
    """
    return {
        parameter.name: parameter.to_physical(
            BOWL_OPTIMUM * (parameter.lower_transformed + parameter.upper_transformed)
        )
        for parameter in parameters
    }


class TestWhereTheOptimumIs:
    def test_the_middle_of_every_interval_costs_nothing(self) -> None:
        outcome = _ask(_bowl(LOG_K, POROSITY), _optimum(LOG_K, POROSITY))

        assert outcome.status == "completed"
        assert outcome.cost == pytest.approx(0.0, abs=1e-24)

    def test_a_log_parameter_is_positioned_geometrically_and_not_arithmetically(self) -> None:
        """``5e-3`` is the middle of ``[1e-6, 1e-2]`` on a ruler and nowhere near it on a log.

        This is the difference between a conductivity read the way it is known
        and one read the way it is written, and it is the reason the bowl asks
        the parameter for its own transform instead of subtracting bounds.
        """
        bowl = _bowl(LOG_K)

        geometric = _ask(bowl, {"k": 1e-4})
        arithmetic = _ask(bowl, {"k": 5e-3})

        assert geometric.cost == pytest.approx(0.0, abs=1e-24)
        assert arithmetic.cost > 0.15

    def test_both_bounds_are_equally_far_from_it(self) -> None:
        bowl = _bowl(LOG_K)

        assert _ask(bowl, {"k": 1e-6}).cost == pytest.approx(BOWL_OPTIMUM**2)
        assert _ask(bowl, {"k": 1e-2}).cost == pytest.approx(BOWL_OPTIMUM**2)

    def test_the_cost_is_the_mean_of_its_components_so_a_dimension_does_not_dilute_it(
        self,
    ) -> None:
        """A sum would make a two-parameter document score twice a one-parameter one."""
        one = _ask(_bowl(LOG_K), {"k": 1e-6})
        two = _ask(_bowl(LOG_K, POROSITY), {"k": 1e-6, "porosity": 0.1})

        assert one.cost == pytest.approx(two.cost)
        assert set(two.components) == {"k", "porosity"}
        assert two.cost == pytest.approx(sum(two.components.values()) / 2)

    def test_a_value_outside_its_bounds_is_scored_and_not_clipped(self) -> None:
        """An optimizer that leaves the box has to be told it is getting worse."""
        bowl = _bowl(POROSITY)

        assert _ask(bowl, {"porosity": 0.4}).cost > _ask(bowl, {"porosity": 0.3}).cost


class TestWhatItRefusesToInvent:
    def test_a_name_the_space_never_declared_fails_and_says_which(self) -> None:
        outcome = _ask(_bowl(LOG_K), {"k": 1e-4, "storage": 1e-3})

        assert outcome.status == "failed"
        assert math.isnan(outcome.cost)
        assert "storage" in str(outcome.error)

    def test_a_value_its_own_transform_cannot_take_fails_rather_than_raising(self) -> None:
        """A negative conductivity has no logarithm, and a search must not stop on one."""
        outcome = _ask(_bowl(LOG_K), {"k": -1.0})

        assert outcome.status == "failed"
        assert math.isnan(outcome.cost)
        assert "log" in str(outcome.error)

    def test_a_sample_that_is_not_a_number_fails_rather_than_costing_nothing(self) -> None:
        outcome = _ask(_bowl(POROSITY), {"porosity": math.nan})

        assert outcome.status == "failed"
        assert math.isnan(outcome.cost)

    def test_a_parameter_the_sample_omits_is_not_scored_against_a_made_up_value(self) -> None:
        """There is nothing to fabricate one from, and fabricating one would move the optimum."""
        outcome = _ask(_bowl(LOG_K, POROSITY), {"k": 1e-4})

        assert outcome.status == "completed"
        assert set(outcome.components) == {"k"}

    def test_an_empty_sample_costs_nothing_and_completes(self) -> None:
        """A document declaring no parameter makes every optimizer ask with ``{}``."""
        outcome = _ask(_bowl(LOG_K), {})

        assert outcome.status == "completed"
        assert outcome.cost == 0.0
        assert outcome.components == {}

    def test_a_pinned_parameter_sits_at_the_optimum_instead_of_dividing_by_zero(self) -> None:
        """Pinning a value is how a document takes a dimension out of a search."""
        pinned = CalibParameter(name="pinned", lower=2.0, upper=2.0)

        outcome = _ask(_bowl(pinned), {"pinned": 2.0})

        assert outcome.status == "completed"
        assert outcome.cost == 0.0

    def test_a_pinned_parameter_takes_a_sample_out_of_the_cost_not_out_of_the_checks(
        self,
    ) -> None:
        """The order the adversarial gate of F9b forced, and the reason it matters.

        A pinned dimension has no interval, so a position read before the value
        was faced returned the optimum for a value nothing can read: ``-5.0``
        under a log transform came back ``completed`` at cost ``0.0`` -- the best
        score the surface has, handed to the sample that deserves it least. Worse
        than the failure mode this port forbids, which is a failed trial carrying
        a large finite number.

        One value and not three on purpose: only a value the *transform* refuses
        goes through the reordered call. ``nan`` and ``inf`` are refused one step
        earlier, and they are asserted in their own test rather than folded in
        here, where they would look like coverage of an order they never reach.
        """
        pinned_log = CalibParameter(name="k", lower=1e-4, upper=1e-4, transform="log")

        outcome = _ask(_bowl(pinned_log), {"k": -5.0})

        assert outcome.status == "failed"
        assert math.isnan(outcome.cost)
        assert "log" in str(outcome.error)

    def test_a_pinned_parameter_refuses_an_infinite_sample_like_any_other(self) -> None:
        """Faced on the value, so having no interval does not exempt it."""
        pinned = CalibParameter(name="pinned", lower=2.0, upper=2.0)
        bowl = _bowl(pinned)

        for unscorable in (math.nan, math.inf, -math.inf):
            outcome = _ask(bowl, {"pinned": unscorable})

            assert outcome.status == "failed", f"{unscorable!r} was scored"
            assert math.isnan(outcome.cost)
            assert outcome.error

    def test_a_value_that_is_not_a_number_at_all_fails_rather_than_raising(self) -> None:
        """``values`` is typed as floats, and a search must not stop on a caller's slip."""
        for unreadable in ("wet", None, [0.2], 10**400):
            outcome = _ask(_bowl(POROSITY), {"porosity": unreadable})

            assert outcome.status == "failed", f"{unreadable!r} did not come back"
            assert math.isnan(outcome.cost)
            assert "not a number this can read" in str(outcome.error)

    def test_a_finite_sample_whose_squared_distance_overflows_fails(self) -> None:
        narrow = CalibParameter(name="narrow", lower=0.0, upper=1e-200)

        outcome = _ask(_bowl(narrow), {"narrow": 1.0})

        assert outcome.status == "failed"
        assert math.isnan(outcome.cost)

    def test_a_mean_uses_finite_terms_without_overflowing_the_sum(self) -> None:
        first = CalibParameter(name="first", lower=0.0, upper=1e-154)
        second = CalibParameter(name="second", lower=0.0, upper=1e-154)

        outcome = _ask(_bowl(first, second), {"first": 1.0, "second": 1.0})

        assert outcome.status == "completed"
        assert outcome.cost == pytest.approx(1e308)


class TestWhatItIsBuiltWith:
    def test_without_a_space_it_says_what_a_space_is_for(self) -> None:
        with pytest.raises(ValueError, match="space"):
            AnalyticBowlEvaluator(space=None)

    def test_the_registry_resolves_it_without_the_workflow_stack_behind_it(self) -> None:
        """The reason it is a built-in and not a test double: a rehearsal has to be cheap."""
        from hydromodpy.calibration.evaluation import registry

        assert registry.get("analytic_bowl") is AnalyticBowlEvaluator
        assert registry.needs_prepared_model("analytic_bowl") is False
        assert "analytic_bowl" in registry.builtin_evaluator_ids()
