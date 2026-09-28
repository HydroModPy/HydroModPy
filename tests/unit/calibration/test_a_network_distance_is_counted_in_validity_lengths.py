"""A normalised network distance is counted in validity lengths.

A network block scores a distance in metres and a hydrograph block an
efficiency, a pure number. Added raw, a phase share table between the two is an
exchange rate between metres and an efficiency. ``normalize_cost = true`` on
``distance_gap`` or ``distance_mean`` divides each distance by the output's
validity length (Eq. 4, ``"auto"`` = 2 h_obs), which the trial publishes, so the
cost is a pure number and a share means a share.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    CalibrationConfig,
    validate_calib_output,
)
from hydromodpy.calibration.metrics.observable_scoring import (
    ObservableScorer,
    network_distance_scales,
)
from hydromodpy.calibration.optim.objective import ConfigBlockObjective
from hydromodpy.core.contracts.observables import ObservableResult


def _gap(scales: dict[str, list[float]] | None, *, metric: str = "distance_gap"):
    return ConfigBlockObjective(
        name="network",
        metric=metric,
        uses_outputs=["net"],
        observed_by_output={},
        normalize_cost=True,
        distance_scales=scales,
    )


class TestTheDeclaration:
    @pytest.mark.parametrize("metric", ["distance_gap", "distance_mean"])
    def test_a_network_distance_may_be_normalised(self, metric: str) -> None:
        block = CalibObjectiveBlockDecl(
            name="network", metric=metric, uses_outputs=["net"], normalize_cost=True
        )
        assert block.normalize_cost is True

    def test_an_efficiency_is_still_refused(self) -> None:
        with pytest.raises(ValueError, match="already a pure number"):
            CalibObjectiveBlockDecl(
                name="q", metric="nse_log", uses_outputs=["q"], normalize_cost=True
            )


class TestTheCost:
    def test_one_bound_is_divided_by_its_validity_length(self) -> None:
        value = _gap({"net": [150.0, 150.0]}).evaluate({"net": [420.0, 120.0]})
        assert value.total == pytest.approx(2.0)
        assert value.components["network.raw_cost"] == pytest.approx(300.0)
        assert value.components["network.normalized_cost"] == pytest.approx(2.0)
        assert value.components["network.reference_scale"] == pytest.approx(150.0)

    def test_the_mean_distance_is_divided_the_same_way(self) -> None:
        value = _gap({"net": [100.0, 100.0]}, metric="distance_mean").evaluate(
            {"net": [300.0, 100.0]}
        )
        assert value.total == pytest.approx(2.0)

    def test_two_bounds_are_each_divided_by_their_own_length(self) -> None:
        scales = {"net": [100.0, 100.0, 200.0, 200.0]}
        value = _gap(scales).evaluate({"net": [50.0, 150.0, 400.0, 0.0]})
        assert value.total == pytest.approx(100.0 / 100.0 + 400.0 / 200.0)
        assert value.components["network.raw_cost"] == pytest.approx(500.0)

    def test_the_sign_a_root_search_reads_is_kept(self) -> None:
        low = _gap({"net": [150.0, 150.0]}).evaluate({"net": [100.0, 400.0]})
        high = _gap({"net": [150.0, 150.0]}).evaluate({"net": [400.0, 100.0]})
        assert low.total == pytest.approx(high.total) == pytest.approx(2.0)

    def test_no_length_published_refuses_the_trial_by_name(self) -> None:
        with pytest.raises(ValueError, match="output 'net' by its validity length"):
            _gap(None).evaluate({"net": [420.0, 120.0]})

    def test_a_length_for_another_count_of_values_is_refused(self) -> None:
        with pytest.raises(ValueError, match="2 for 4 values"):
            _gap({"net": [150.0, 150.0]}).evaluate({"net": [1.0, 2.0, 3.0, 4.0]})

    def test_a_length_that_is_not_positive_is_refused(self) -> None:
        with pytest.raises(ValueError, match="positive length"):
            _gap({"net": [0.0, 0.0]}).evaluate({"net": [420.0, 120.0]})


class TestTheLengthsATrialPublishes:
    NETWORK = validate_calib_output({"support": "network", "stream_geometry_path": "n.gpkg"})

    def test_one_bound_reads_its_unsuffixed_length(self) -> None:
        found = network_distance_scales(
            {"net": self.NETWORK},
            {"net.n_bounds_scored": 1.0, "net.validity_length_m": 150.0},
        )
        assert found == {"net": [150.0, 150.0]}

    def test_two_bounds_read_the_minimal_then_the_maximal(self) -> None:
        found = network_distance_scales(
            {"net": self.NETWORK},
            {
                "net.n_bounds_scored": 2.0,
                "net.validity_length_m_minimal": 100.0,
                "net.validity_length_m_maximal": 200.0,
            },
        )
        assert found == {"net": [100.0, 100.0, 200.0, 200.0]}

    def test_an_output_that_published_none_is_left_out(self) -> None:
        assert network_distance_scales({"net": self.NETWORK}, {}) == {}


class TestAShareIsAShare:
    """A phase table between a network block and an efficiency weighs pure numbers."""

    def _scorer(self) -> ObservableScorer:
        outputs = {
            "net": validate_calib_output({"support": "network", "stream_geometry_path": "n.gpkg"}),
            "q": validate_calib_output(
                {
                    "support": "boundary",
                    "variable": "discharge",
                    "boundary_id": "outlet",
                    "observed_values": [1.0, 2.0, 3.0, 4.0],
                }
            ),
        }
        blocks = [
            CalibObjectiveBlockDecl(
                name="network",
                metric="distance_gap",
                uses_outputs=["net"],
                normalize_cost=True,
                weight=0.2,
            ),
            CalibObjectiveBlockDecl(
                name="hydrograph", metric="nse", uses_outputs=["q"], weight=0.8
            ),
        ]
        return ObservableScorer(outputs, blocks)

    def test_the_network_enters_the_sum_in_validity_lengths(self) -> None:
        simulated = ObservableResult(
            request_id="q", values=np.array([1.0, 2.0, 3.0, 4.0]), units="m3 s-1"
        )
        total, components = self._scorer().score(
            {"q": simulated},
            network_values={"net": [450.0, 150.0]},
            diagnostics={"net.n_bounds_scored": 1.0, "net.validity_length_m": 150.0},
        )
        assert components["network.total"] == pytest.approx(2.0)
        assert components["hydrograph.total"] == pytest.approx(0.0)
        assert total == pytest.approx(0.2 * 2.0)

    def test_a_trial_that_published_no_length_is_not_scored(self) -> None:
        simulated = ObservableResult(
            request_id="q", values=np.array([1.0, 2.0, 3.0, 4.0]), units="m3 s-1"
        )
        with pytest.raises(RuntimeError, match="validity length"):
            self._scorer().score({"q": simulated}, network_values={"net": [450.0, 150.0]})


class TestTheUnitsOfASum:
    def _config(self, blocks: list[dict[str, object]]) -> dict[str, object]:
        return {
            "parameters": {"K": {"bounds": [1e-8, 1e-2]}},
            "outputs": {
                "net": {"support": "network", "stream_geometry_path": "n.gpkg"},
                "head": {
                    "variable": "head",
                    "support": "cell",
                    "row": 0,
                    "col": 0,
                    "observed_values": [1.0, 2.0],
                },
            },
            "objective_blocks": blocks,
        }

    def test_a_raw_distance_beside_a_raw_head_residual_is_refused(self) -> None:
        with pytest.raises(ValueError) as caught:
            CalibrationConfig.model_validate(
                self._config(
                    [
                        {"name": "network", "metric": "distance_gap", "uses_outputs": ["net"]},
                        {"name": "heads", "metric": "rmse", "uses_outputs": ["head"]},
                    ]
                )
            )
        message = str(caught.value)
        assert "network distance in m" in message
        assert "validity lengths" in message

    def test_both_normalised_they_add(self) -> None:
        cfg = CalibrationConfig.model_validate(
            self._config(
                [
                    {
                        "name": "network",
                        "metric": "distance_gap",
                        "uses_outputs": ["net"],
                        "normalize_cost": True,
                    },
                    {
                        "name": "heads",
                        "metric": "rmse",
                        "uses_outputs": ["head"],
                        "normalize_cost": True,
                    },
                ]
            )
        )
        assert len(cfg.objective_blocks) == 2


class TestTheIntervalOfANormalisedDistance:
    """A distance counted in validity lengths is no longer read in mesh cells."""

    def _config(self, *, normalise: bool) -> CalibrationConfig:
        return CalibrationConfig.model_validate(
            {
                "parameters": {"K": {"bounds": [1e-8, 1e-2]}},
                "outputs": {"net": {"support": "network", "stream_geometry_path": "n.gpkg"}},
                "objective_blocks": [
                    {
                        "name": "network",
                        "metric": "distance_gap",
                        "uses_outputs": ["net"],
                        "normalize_cost": normalise,
                    }
                ],
            }
        )

    def test_a_gap_in_metres_is_read_in_mesh_cells(self) -> None:
        width = self._config(normalise=False).interval_width_for()
        assert width.on_distances is True
        assert width.mode == "absolute"

    def test_a_normalised_gap_is_read_as_any_other_cost(self) -> None:
        width = self._config(normalise=True).interval_width_for()
        assert width.on_distances is False
        assert width.mode == "relative"
