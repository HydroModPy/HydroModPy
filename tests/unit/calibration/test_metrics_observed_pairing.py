"""Tests of `metrics.observed_pairing`."""

from __future__ import annotations

import inspect

import pandas as pd
import pytest

from hydromodpy.calibration.config import CalibAggregateDecl, CalibrationConfig
from hydromodpy.calibration.metrics.observed_pairing import pair_outputs_with_observations
from hydromodpy.calibration.runners import pipeline_evaluator

# From test_the_aggregation_is_declared.py
# How several targets become one cost: the fewest pairs a member is scored on.
#
# ``weighting``, ``nested_gauges`` and ``on_member_failure`` were declared here
# and never read, so a file that wrote ``weighting = "error"`` or
# ``on_member_failure = "drop"`` got the same cost as one that did not. They
# are refused, and ``hmp doctor --fix-config`` deletes them.


def _config(aggregate: dict[str, object], **over: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "parameters": {"K": {"bounds": [1e-8, 1e-2]}},
        "outputs": {
            "q": {
                "variable": "discharge",
                "support": "boundary",
                "boundary_id": "outlet",
                "observes": "J7branch",
            }
        },
        "objective_blocks": [{"name": "flows", "metric": "rmse", "uses_outputs": ["q"]}],
        "aggregate": aggregate,
    }
    payload.update(over)
    return payload


class TestTheDefaults:
    def test_one_pair_is_enough_by_default(self) -> None:
        assert CalibAggregateDecl().min_samples == 1

    def test_a_calibration_carries_one_by_default(self) -> None:
        cfg = CalibrationConfig.model_validate({"parameters": {"K": {"bounds": [1e-8, 1e-2]}}})

        assert cfg.aggregate.min_samples == 1


class TestTheRefusedKeys:
    @pytest.mark.parametrize(
        ("key", "value"),
        [("weighting", "error"), ("nested_gauges", "incremental"), ("on_member_failure", "drop")],
    )
    def test_an_aggregate_key_nothing_read_is_refused(self, key: str, value: str) -> None:
        with pytest.raises(ValueError, match=rf"'{key}' is not accepted any more.*deletes it"):
            CalibrationConfig.model_validate(_config({key: value}))

        assert key not in CalibAggregateDecl.model_fields

    @pytest.mark.parametrize(
        "key", ["lightweight_extraction", "persist_model_distribution", "persistence"]
    )
    def test_a_section_key_nothing_read_is_refused(self, key: str) -> None:
        with pytest.raises(ValueError, match=rf"'{key}' is not accepted any more.*deletes it"):
            CalibrationConfig.model_validate({key: True})

        assert key not in CalibrationConfig.model_fields


class TestWhatItRefuses:
    def test_a_min_samples_below_one_is_refused(self) -> None:
        with pytest.raises(ValueError):
            CalibrationConfig.model_validate(_config({"min_samples": 0}))


class TestMinSamplesReachesThePairing:
    def test_an_overlap_below_the_floor_is_refused_by_name(self) -> None:
        times = pd.date_range("2000-01-01", periods=3, freq="D")
        with pytest.raises(ValueError, match="min_samples"):
            pair_outputs_with_observations(
                observed={"q": pd.Series([1.0, 2.0, 3.0], index=times)},
                simulated={"q": pd.Series([1.1, 2.1, 3.1], index=times)},
                min_samples=10,
            )

    def test_an_overlap_at_the_floor_is_accepted(self) -> None:
        # Each simulated stamp closes the day observed one day before it.
        paired = pair_outputs_with_observations(
            observed={
                "q": pd.Series([1.0, 2.0, 3.0], index=pd.date_range("1999-12-31", periods=3))
            },
            simulated={
                "q": pd.Series([1.1, 2.1, 3.1], index=pd.date_range("2000-01-01", periods=3))
            },
            min_samples=3,
        )

        assert paired.n_paired["q"] == 3

    def test_the_evaluator_forwards_what_the_file_declared(self) -> None:
        """Where the metric extractor is built is where the declaration is read.

        It is built by the evaluator that runs the pipeline, because building it
        needs that evaluator's trial context.
        """

        source = inspect.getsource(pipeline_evaluator._extractor_for)

        assert "min_samples=int(cfg.aggregate.min_samples)" in source
