"""A criterion that balances two simulated quantities has nothing to fit.

The stream-network criterion measures the descent from the simulated seepage
network to the mapped one and, reciprocally, from the mapped one back. Both are
simulated. Its cost is the imbalance between them, so there is no observed
series anywhere in it.

The objective could only score a block by pairing a simulated vector with an
observed one, so the output declared ``observed_values = [0, 0]`` and every
scoring path went through that fabrication: the length check compared against
it, the reference scale was read off it, and a reader of the schema was told a
network output has observations. Two zeros that mean "there is nothing here" are
a worse answer than saying so.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.config import CalibOutputNetwork, validate_calib_output
from hydromodpy.calibration.optim.objective import (
    CRITERION_METRICS,
    ConfigBlockObjective,
    build_objective_from_config,
)


def _network_output() -> CalibOutputNetwork:
    return validate_calib_output({"support": "network", "stream_geometry_path": "streams.gpkg"})


class TestTheDeclaration:
    def test_a_network_output_declares_no_observed_values(self) -> None:
        assert "observed_values" not in CalibOutputNetwork.model_fields

    def test_writing_them_is_refused_rather_than_ignored(self) -> None:
        with pytest.raises(ValueError):
            validate_calib_output(
                {
                    "support": "network",
                    "stream_geometry_path": "streams.gpkg",
                    "observed_values": [0.0, 0.0],
                }
            )


class TestTheMetrics:
    def test_the_distances_are_listed_as_criterion_metrics(self) -> None:
        assert {"distance_gap", "distance_mean"} == CRITERION_METRICS

    def test_a_block_on_a_criterion_metric_needs_no_observed_vector(self) -> None:
        block = ConfigBlockObjective(
            name="gap", metric="distance_gap", uses_outputs=["net"], observed_by_output={}
        )

        value = block.evaluate({"net": [120.0, 100.0]})

        assert value.total == pytest.approx(20.0)

    def test_the_mean_reads_the_same_pair(self) -> None:
        block = ConfigBlockObjective(
            name="mean", metric="distance_mean", uses_outputs=["net"], observed_by_output={}
        )

        assert block.evaluate({"net": [120.0, 100.0]}).total == pytest.approx(110.0)

    def test_a_pair_that_is_not_a_pair_is_refused(self) -> None:
        block = ConfigBlockObjective(
            name="gap", metric="distance_gap", uses_outputs=["net"], observed_by_output={}
        )

        with pytest.raises(ValueError, match="pair"):
            block.evaluate({"net": [1.0, 2.0, 3.0]})

    def test_an_ordinary_metric_still_needs_its_observations(self) -> None:
        with pytest.raises(ValueError, match="observed"):
            ConfigBlockObjective(
                name="q", metric="rmse", uses_outputs=["out"], observed_by_output={}
            )


class TestTheAssembly:
    def test_a_configuration_declaring_only_a_criterion_block_builds(self) -> None:
        from types import SimpleNamespace

        from hydromodpy.calibration.config import CalibObjectiveBlockDecl

        objective = build_objective_from_config(
            SimpleNamespace(
                outputs={"net": _network_output()},
                objective_blocks=[
                    CalibObjectiveBlockDecl(name="gap", metric="distance_gap", uses_outputs=["net"])
                ],
                warmup_periods=0,
            )
        )

        assert objective.evaluate({"net": np.array([120.0, 100.0])}).total == pytest.approx(20.0)

    def test_a_burn_in_on_a_criterion_block_is_still_refused(self) -> None:
        """It carries no time axis to drop the first periods of."""
        with pytest.raises(ValueError, match="no time axis"):
            ConfigBlockObjective(
                name="gap",
                metric="distance_gap",
                uses_outputs=["net"],
                observed_by_output={},
                warmup=2,
                timeless_outputs=["net"],
            )
