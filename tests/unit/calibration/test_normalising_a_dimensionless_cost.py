"""Normalising a cost that has no unit distorts the weighting it was meant to fix.

``normalize_cost`` divides a block's cost by a reference scale read off the
observed vector. It exists so that a composite sum does not let the unit decide
the weighting: an RMSE on heads is in metres, one on discharge in m3/s, and
adding them raw gives the metres a say the weights never granted.

An efficiency score has no unit to remove. NSE, KGE, nse_log, nse_delta,
nse_seasonal and the reservoir score are already dimensionless numbers, so
dividing them by the standard deviation of the observations does not put two
costs on a common footing: it multiplies one block's weight by a number that
belongs to its data, silently. Two blocks written with equal weights come out
unequal, and nothing in the report says by how much.

The network distances have a unit, metres, but no observed vector to take a
scale from: their reference collapses to one and the normalisation is a no-op
wearing the name of a correction.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.optim.objective import (
    DIMENSIONLESS_METRICS,
    ConfigBlockObjective,
)

_OBSERVED = {"q": (1.0, 2.0, 3.0)}


def _block(metric: str, *, normalize: bool) -> ConfigBlockObjective:
    return ConfigBlockObjective(
        name="b",
        metric=metric,
        uses_outputs=["q"],
        observed_by_output=_OBSERVED,
        normalize_cost=normalize,
    )


class TestWhichMetricsHaveNoUnit:
    def test_the_efficiency_scores_are_listed(self) -> None:
        assert {"nse", "kge", "nse_log", "nse_delta", "nse_seasonal", "reservoir"} <= (
            DIMENSIONLESS_METRICS
        )

    def test_a_residual_metric_is_not(self) -> None:
        assert "rmse" not in DIMENSIONLESS_METRICS
        assert "mae" not in DIMENSIONLESS_METRICS


class TestWhatIsRefused:
    @pytest.mark.parametrize("metric", ["nse", "kge", "nse_log", "reservoir"])
    def test_normalising_an_efficiency_score_is_refused(self, metric: str) -> None:
        with pytest.raises(ValueError, match="normalize_cost"):
            _block(metric, normalize=True)

    def test_the_refusal_names_the_metric_and_what_to_do(self) -> None:
        with pytest.raises(ValueError) as caught:
            _block("nse", normalize=True)

        message = str(caught.value)
        assert "nse" in message
        assert "weight" in message

    def test_normalising_a_network_distance_is_refused(self) -> None:
        """Its reference scale comes from a pair of zeros and collapses to one."""
        with pytest.raises(ValueError, match="distance_gap"):
            ConfigBlockObjective(
                name="net",
                metric="distance_gap",
                uses_outputs=["net"],
                observed_by_output={"net": (0.0, 0.0)},
                normalize_cost=True,
            )


class TestWhatIsUntouched:
    @pytest.mark.parametrize("metric", ["rmse", "mae"])
    def test_normalising_a_residual_metric_still_works(self, metric: str) -> None:
        assert _block(metric, normalize=True) is not None

    @pytest.mark.parametrize("metric", ["nse", "kge", "rmse", "distance_gap"])
    def test_leaving_it_off_is_always_fine(self, metric: str) -> None:
        assert (
            ConfigBlockObjective(
                name="b",
                metric=metric,
                uses_outputs=["q"],
                observed_by_output=_OBSERVED,
                normalize_cost=False,
            )
            is not None
        )


class TestWhereTheRefusalHappens:
    """The reader writes TOML, so the file is where the refusal belongs."""

    def test_the_file_is_refused_when_it_is_read(self) -> None:
        from hydromodpy.calibration.config import CalibObjectiveBlockDecl

        with pytest.raises(ValueError, match="normalize_cost"):
            CalibObjectiveBlockDecl(name="b", metric="nse", uses_outputs=["q"], normalize_cost=True)

    def test_a_residual_block_still_loads(self) -> None:
        from hydromodpy.calibration.config import CalibObjectiveBlockDecl

        block = CalibObjectiveBlockDecl(
            name="b", metric="rmse", uses_outputs=["q"], normalize_cost=True
        )

        assert block.normalize_cost is True
