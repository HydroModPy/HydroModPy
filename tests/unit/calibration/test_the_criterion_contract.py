"""A criterion declares what it needs and returns what it found.

An objective was a function ``f(sim, obs) -> float``. That fits a series and
nothing else, so a criterion comparing two geometries disguised itself as one:
a two-element vector standing in for a series, a vector of zeros standing in for
observations it does not have, and a free-text component name standing in for
"this one publishes a signed residual". Five artefacts held one shape open.

The gate that matters is the last class here: every cost must come out of the
contract bit for bit identical to the cost the inline path produced, or the
refactor changed what is optimised.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.criteria import (
    NetworkCriterion,
    SeriesCriterion,
    available_criteria,
    criterion_for,
)
from hydromodpy.calibration.optim.objective import HIGHER_IS_BETTER, METRICS

# Long enough that the seasonal kernels return a number rather than NaN: they
# read a cycle out of the samples themselves.
_N = 96
_SIM = 5.0 + 3.0 * np.sin(np.arange(_N) * 2.0 * np.pi / 12.0) + 0.05 * np.arange(_N)
_OBS = 5.0 + 3.0 * np.sin((np.arange(_N) + 0.4) * 2.0 * np.pi / 12.0) + 0.04 * np.arange(_N)


def _same_number(left: float, right: float) -> bool:
    """Equality that also holds for a kernel whose cost is legitimately NaN."""
    if np.isnan(left) and np.isnan(right):
        return True
    return left == right


class TestTheRegistry:
    def test_every_kernel_is_reachable_by_name(self) -> None:
        assert set(available_criteria()) == set(METRICS)

    def test_an_unknown_name_is_refused_with_the_list(self) -> None:
        with pytest.raises(ValueError, match="Registered"):
            criterion_for("nse_squared")

    def test_a_series_kernel_yields_a_series_criterion(self) -> None:
        assert isinstance(criterion_for("nse"), SeriesCriterion)

    def test_a_network_estimator_yields_the_network_criterion(self) -> None:
        assert isinstance(criterion_for("distance_gap"), NetworkCriterion)


class TestWhatASeriesCriterionDeclares:
    def test_it_fits_observations_and_carries_a_time_axis(self) -> None:
        needs = criterion_for("nse").requirements()

        assert needs.needs_observations is True
        assert needs.has_time_axis is True

    def test_no_series_criterion_publishes_a_signed_residual(self) -> None:
        for name in METRICS:
            if name in {"distance_gap", "distance_mean"}:
                continue
            assert criterion_for(name).requirements().signed is False, name

    def test_an_efficiency_score_says_its_cost_has_no_unit(self) -> None:
        needs = criterion_for("kge").requirements()

        assert needs.cost_is_dimensionless is True
        assert needs.cost_unit is None

    def test_a_residual_metric_says_its_cost_carries_one(self) -> None:
        needs = criterion_for("rmse").requirements()

        assert needs.cost_is_dimensionless is False
        assert needs.cost_unit is not None

    def test_scoring_without_observations_is_refused(self) -> None:
        with pytest.raises(ValueError, match="observations"):
            criterion_for("rmse").score(_SIM)

    def test_a_length_mismatch_is_refused_by_name(self) -> None:
        with pytest.raises(ValueError, match="rmse"):
            criterion_for("rmse").score(_SIM, _OBS[:3])

    def test_a_log_metric_reports_what_it_clipped(self) -> None:
        result = criterion_for("nse_log").score(np.array([-1.0, 2.0, 3.0]), _OBS[:3])

        assert result.diagnostics["n_clipped"] == 1.0


class TestWhatTheNetworkCriterionDeclares:
    def test_it_needs_no_observations_and_has_no_time_axis(self) -> None:
        needs = criterion_for("distance_gap").requirements()

        assert needs.needs_observations is False
        assert needs.has_time_axis is False

    def test_the_gap_publishes_the_signed_residual_its_cost_is_built_from(self) -> None:
        needs = criterion_for("distance_gap").requirements()
        result = criterion_for("distance_gap").score([120.0, 100.0])

        assert needs.signed is True
        assert result.cost == pytest.approx(20.0)
        assert result.signed_residual == pytest.approx(20.0)

    def test_the_sign_survives_a_reversal(self) -> None:
        result = criterion_for("distance_gap").score([100.0, 120.0])

        assert result.cost == pytest.approx(20.0)
        assert result.signed_residual == pytest.approx(-20.0)

    def test_the_mean_publishes_none_because_its_cost_is_not_that_residual(self) -> None:
        needs = criterion_for("distance_mean").requirements()
        result = criterion_for("distance_mean").score([120.0, 100.0])

        assert needs.signed is False
        assert result.signed_residual is None
        assert result.cost == pytest.approx(110.0)

    def test_its_cost_is_in_metres(self) -> None:
        assert criterion_for("distance_gap").requirements().cost_unit == "m"

    def test_it_reports_the_pair_it_read(self) -> None:
        diagnostics = criterion_for("distance_gap").score([120.0, 100.0]).diagnostics

        assert diagnostics["D_so"] == pytest.approx(120.0)
        assert diagnostics["D_os"] == pytest.approx(100.0)

    def test_a_series_is_not_a_pair(self) -> None:
        with pytest.raises(ValueError, match="pair"):
            criterion_for("distance_gap").score([1.0, 2.0, 3.0])


class TestTheCostsAreUnchanged:
    """The gate: the contract must not move a single cost."""

    @staticmethod
    def _inline_cost(name: str) -> float:
        """Reproduce exactly what the objective did before the contract."""
        from hydromodpy.calibration.optim.objective import (
            LOG_METRICS,
            clip_negatives_for_log_metric,
        )

        sim, obs = _SIM, _OBS
        if name in LOG_METRICS:
            sim, obs, _ = clip_negatives_for_log_metric(sim, obs)
        raw = float(METRICS[name](sim, obs))
        return (1.0 - raw) if name in HIGHER_IS_BETTER else raw

    @pytest.mark.parametrize("name", sorted(set(METRICS) - {"distance_gap", "distance_mean"}))
    def test_a_series_cost_is_identical_to_the_bit(self, name: str) -> None:
        through_contract = criterion_for(name).score(_SIM, _OBS).cost

        assert _same_number(through_contract, self._inline_cost(name))

    @pytest.mark.parametrize("name", ["distance_gap", "distance_mean"])
    def test_a_network_cost_is_identical_to_the_bit(self, name: str) -> None:
        pair = np.array([137.5, 91.25])

        assert _same_number(criterion_for(name).score(pair).cost, float(METRICS[name](pair)))
