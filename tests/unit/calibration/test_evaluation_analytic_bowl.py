"""The analytic bowl, a model-free cost surface used to rehearse a search.

The cost is the mean over parameters of the squared distance to the middle of each
interval, taken on the search scale of the parameter (log for a conductivity).
A sample the bowl cannot score comes back as a failed trial carrying nan.
"""

from __future__ import annotations

import math

import pytest

from hydromodpy.calibration.evaluation.analytic_bowl import BOWL_OPTIMUM, AnalyticBowlEvaluator
from hydromodpy.calibration.evaluation.port import TrialRequest
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace

pytestmark = pytest.mark.fast

LOG_K = CalibParameter(name="k", lower=1e-6, upper=1e-2, search_space="log")
POROSITY = CalibParameter(name="porosity", lower=0.1, upper=0.3)
PINNED = CalibParameter(name="pinned", lower=2.0, upper=2.0)
PINNED_LOG = CalibParameter(name="k", lower=1e-4, upper=1e-4, search_space="log")
NARROW = CalibParameter(name="narrow", lower=0.0, upper=1e-200)
SLIVER = CalibParameter(name="sliver", lower=0.0, upper=1e-320)


def ask(values: dict, *parameters: CalibParameter):
    bowl = AnalyticBowlEvaluator(space=ParameterSpace(parameters))
    return bowl.evaluate(TrialRequest(trial_id=1, values=values))


def optimum(*parameters: CalibParameter) -> dict[str, float]:
    # Read off the bounds: 0.2 and the midpoint of [0.1, 0.3] are two different floats.
    return {
        parameter.name: parameter.to_physical(
            BOWL_OPTIMUM * (parameter.lower_transformed + parameter.upper_transformed)
        )
        for parameter in parameters
    }


def test_middle_of_every_interval_costs_nothing() -> None:
    outcome = ask(optimum(LOG_K, POROSITY), LOG_K, POROSITY)

    assert outcome.status == "completed"
    assert outcome.cost == pytest.approx(0.0, abs=1e-24)


def test_log_parameter_is_positioned_geometrically() -> None:
    # 5e-3 is the middle of [1e-6, 1e-2] on a ruler and nowhere near it on a log scale.
    assert ask({"k": 1e-4}, LOG_K).cost == pytest.approx(0.0, abs=1e-24)
    assert ask({"k": 5e-3}, LOG_K).cost > 0.15


@pytest.mark.parametrize("k_m_s", [1e-6, 1e-2])
def test_both_bounds_are_equally_far(k_m_s: float) -> None:
    assert ask({"k": k_m_s}, LOG_K).cost == pytest.approx(BOWL_OPTIMUM**2)


def test_cost_is_the_mean_of_its_components() -> None:
    # A sum would make a two-parameter document score twice a one-parameter one.
    one = ask({"k": 1e-6}, LOG_K)
    two = ask({"k": 1e-6, "porosity": 0.1}, LOG_K, POROSITY)

    assert one.cost == pytest.approx(two.cost)
    assert set(two.components) == {"k", "porosity"}
    assert two.cost == pytest.approx(sum(two.components.values()) / 2)


@pytest.mark.parametrize(
    ("values", "parameters", "said"),
    [
        pytest.param({"k": 1e-4, "storage": 1e-3}, [LOG_K], "storage", id="undeclared name"),
        pytest.param({"k": -1.0}, [LOG_K], "log", id="negative value on a log scale"),
        pytest.param({"porosity": math.nan}, [POROSITY], "", id="nan"),
        # A pinned parameter has no interval, yet its value is still checked.
        pytest.param({"k": -5.0}, [PINNED_LOG], "log", id="pinned log refuses a negative"),
        pytest.param({"pinned": math.nan}, [PINNED], "", id="pinned nan"),
        pytest.param({"pinned": math.inf}, [PINNED], "", id="pinned inf"),
        pytest.param({"pinned": -math.inf}, [PINNED], "", id="pinned minus inf"),
        pytest.param({"porosity": "wet"}, [POROSITY], "not a number this can read", id="a string"),
        pytest.param({"porosity": None}, [POROSITY], "not a number this can read", id="none"),
        pytest.param({"porosity": [0.2]}, [POROSITY], "not a number this can read", id="a list"),
        pytest.param(
            {"porosity": 10**400}, [POROSITY], "not a number this can read", id="huge int"
        ),
        pytest.param({"narrow": 1.0}, [NARROW], "", id="squared distance overflows"),
        pytest.param({"sliver": 1.0}, [SLIVER], "does not land anywhere", id="position overflows"),
    ],
)
def test_unscorable_sample_fails(values: dict, parameters: list, said: str) -> None:
    outcome = ask(values, *parameters)

    assert outcome.status == "failed"
    assert math.isnan(outcome.cost)
    assert said in str(outcome.error)


def test_empty_sample_costs_nothing() -> None:
    # A document with no parameter makes every optimizer ask with {}.
    outcome = ask({}, LOG_K)

    assert (outcome.status, outcome.cost, outcome.components) == ("completed", 0.0, {})


def test_pinned_parameter_sits_at_the_optimum() -> None:
    outcome = ask({"pinned": 2.0}, PINNED)

    assert (outcome.status, outcome.cost) == ("completed", 0.0)


def test_mean_uses_finite_terms_without_overflowing_the_sum() -> None:
    first = CalibParameter(name="first", lower=0.0, upper=1e-154)
    second = CalibParameter(name="second", lower=0.0, upper=1e-154)

    outcome = ask({"first": 1.0, "second": 1.0}, first, second)

    assert outcome.status == "completed"
    assert outcome.cost == pytest.approx(1e308)


def test_refuses_a_missing_space() -> None:
    with pytest.raises(ValueError, match="space"):
        AnalyticBowlEvaluator(space=None)
