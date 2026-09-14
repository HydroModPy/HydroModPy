"""How several targets become one cost must be written, not assumed.

Two questions the word "weight" runs together. Whether an error is large *for
what the instrument can resolve* is a property of the measurement, not a
decision. What matters more between the outlet and the reservoir is a decision,
and the modeller's. The cost is the product of both, never one of them.

The literature offers exactly two named recipes and says they are incompatible:
one over sigma, which makes each residual dimensionless and defensible, and an
equal share of the initial objective, which guarantees no data type is invisible.
There is no third to invent. There is a choice to name and to record, which is
what this section is for.

``nested_gauges`` is the other declaration. Two gauges on imbricated catchments
are not double counting, but their residuals are statistically dependent, and no
standard correction exists. The only mechanisable rule is to read the downstream
one incrementally, and either way the choice is written rather than inferred.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import CalibAggregateDecl, CalibrationConfig


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
    def test_nothing_is_assumed_about_the_weighting(self) -> None:
        decl = CalibAggregateDecl()

        assert decl.weighting == "manual"
        assert decl.nested_gauges == "total"
        assert decl.on_member_failure == "veto"
        assert decl.min_samples == 1

    def test_a_calibration_carries_one_by_default(self) -> None:
        cfg = CalibrationConfig.model_validate({"parameters": {"K": {"bounds": [1e-8, 1e-2]}}})

        assert cfg.aggregate.weighting == "manual"


class TestWhatItAccepts:
    def test_an_error_weighting_on_a_residual_criterion_loads(self) -> None:
        cfg = CalibrationConfig.model_validate(_config({"weighting": "error"}))

        assert cfg.aggregate.weighting == "error"

    def test_reading_a_nested_gauge_incrementally_loads(self) -> None:
        cfg = CalibrationConfig.model_validate(_config({"nested_gauges": "incremental"}))

        assert cfg.aggregate.nested_gauges == "incremental"

    def test_dropping_a_failed_member_loads(self) -> None:
        cfg = CalibrationConfig.model_validate(_config({"on_member_failure": "drop"}))

        assert cfg.aggregate.on_member_failure == "drop"


class TestWhatItRefuses:
    def test_an_error_weighting_on_a_dimensionless_score_is_refused(self) -> None:
        """One over sigma divides a residual. An efficiency score is not one."""
        with pytest.raises(ValueError, match="error"):
            CalibrationConfig.model_validate(
                _config(
                    {"weighting": "error"},
                    objective_blocks=[
                        {"name": "flows", "metric": "nse_log", "uses_outputs": ["q"]}
                    ],
                )
            )

    def test_the_refusal_names_the_block_and_the_metric(self) -> None:
        with pytest.raises(ValueError) as caught:
            CalibrationConfig.model_validate(
                _config(
                    {"weighting": "error"},
                    objective_blocks=[{"name": "flows", "metric": "kge", "uses_outputs": ["q"]}],
                )
            )

        message = str(caught.value)
        assert "flows" in message
        assert "kge" in message

    def test_an_error_weighting_with_no_loaded_record_is_refused(self) -> None:
        """Sigma comes from an observation; a typed vector carries none."""
        with pytest.raises(ValueError, match="observes"):
            CalibrationConfig.model_validate(
                _config(
                    {"weighting": "error"},
                    outputs={
                        "q": {
                            "variable": "discharge",
                            "support": "boundary",
                            "boundary_id": "outlet",
                            "observed_values": [1.0, 2.0],
                        }
                    },
                )
            )

    def test_a_min_samples_below_one_is_refused(self) -> None:
        with pytest.raises(ValueError):
            CalibrationConfig.model_validate(_config({"min_samples": 0}))

    def test_an_unknown_weighting_is_refused(self) -> None:
        with pytest.raises(ValueError):
            CalibrationConfig.model_validate(_config({"weighting": "inverse_variance_ish"}))

    def test_an_unknown_nested_reading_is_refused(self) -> None:
        with pytest.raises(ValueError):
            CalibrationConfig.model_validate(_config({"nested_gauges": "subtract_maybe"}))


class TestMinSamplesReachesThePairing:
    def test_an_overlap_below_the_floor_is_refused_by_name(self) -> None:
        import pandas as pd

        from hydromodpy.calibration.metrics.observed_pairing import (
            pair_outputs_with_observations,
        )

        times = pd.date_range("2000-01-01", periods=3, freq="D")
        with pytest.raises(ValueError, match="min_samples"):
            pair_outputs_with_observations(
                observed={"q": pd.Series([1.0, 2.0, 3.0], index=times)},
                simulated={"q": pd.Series([1.1, 2.1, 3.1], index=times)},
                min_samples=10,
            )

    def test_an_overlap_at_the_floor_is_accepted(self) -> None:
        import pandas as pd

        from hydromodpy.calibration.metrics.observed_pairing import (
            pair_outputs_with_observations,
        )

        times = pd.date_range("2000-01-01", periods=3, freq="D")
        paired = pair_outputs_with_observations(
            observed={"q": pd.Series([1.0, 2.0, 3.0], index=times)},
            simulated={"q": pd.Series([1.1, 2.1, 3.1], index=times)},
            min_samples=3,
        )

        assert paired.n_paired["q"] == 3

    def test_the_runner_forwards_what_the_file_declared(self) -> None:
        import inspect

        from hydromodpy.calibration.runners import cli_runner

        source = inspect.getsource(cli_runner.run_calibration_core)

        assert "min_samples=int(cfg.aggregate.min_samples)" in source
