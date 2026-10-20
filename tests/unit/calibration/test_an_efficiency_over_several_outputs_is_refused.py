"""An efficiency is one number per station, and the costs are averaged.

A block over several outputs concatenates them and computes one metric on the
pool. For an error (rmse, mae) the pool is a fair summary. For an efficiency
(nse, kge, ...) it is not: the observed variance of the pool is dominated by the
differences between stations, so a station that is badly simulated hides behind
the spread between the others. A probe gave a pooled cost of 0.006 against 0.82
once averaged per station.

A metric that rises with the fit therefore takes one output per block. Writing
one block per output, each with its weight, averages the costs per station.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibObjectiveBlockDecl, CalibrationConfig
from hydromodpy.calibration.criteria.series import METRICS
from hydromodpy.results.catalog.constants import METRIC_SENSE

EFFICIENCIES = sorted(name for name in METRICS if METRIC_SENSE.get(name) == "max")
POOLABLE = sorted(name for name in METRICS if METRIC_SENSE.get(name) == "min")


def _config(blocks: list[dict[str, object]]) -> dict[str, object]:
    series = {"variable": "discharge", "support": "boundary", "observed_values": [1.0, 2.0, 3.0]}
    return {
        "parameters": {"K": {"bounds": [1e-8, 1e-2]}},
        "outputs": {
            "upstream": {**series, "boundary_id": "up"},
            "downstream": {**series, "boundary_id": "down"},
        },
        "objective_blocks": blocks,
    }


def _block(metric: str, outputs: list[str], **extra: object) -> dict[str, object]:
    return {"name": "stations", "metric": metric, "uses_outputs": outputs, **extra}


def test_the_efficiencies_are_found_in_the_metric_table() -> None:
    assert {"nse", "nse_log", "kge"} <= set(EFFICIENCIES)
    assert {"rmse", "mae"} <= set(POOLABLE)


@pytest.mark.parametrize("metric", EFFICIENCIES)
def test_an_efficiency_over_two_outputs_is_refused(metric: str) -> None:
    with pytest.raises(ValidationError) as caught:
        CalibObjectiveBlockDecl.model_validate(_block(metric, ["upstream", "downstream"]))

    message = str(caught.value)
    assert "stations" in message
    assert "upstream" in message and "downstream" in message
    assert "one block per output" in message


def test_the_refusal_reaches_a_whole_calibration_file() -> None:
    blocks = [_block("nse", ["upstream", "downstream"])]

    with pytest.raises(ValidationError, match="one block per output"):
        CalibrationConfig.model_validate(_config(blocks))


@pytest.mark.parametrize("metric", EFFICIENCIES)
def test_one_block_per_output_is_accepted_with_its_weight(metric: str) -> None:
    blocks = [
        {"name": "up", "metric": metric, "uses_outputs": ["upstream"], "weight": 2.0},
        {"name": "down", "metric": metric, "uses_outputs": ["downstream"], "weight": 1.0},
    ]

    config = CalibrationConfig.model_validate(_config(blocks))

    assert [b.weight for b in config.objective_blocks] == [2.0, 1.0]


@pytest.mark.parametrize("metric", EFFICIENCIES)
def test_an_efficiency_over_one_output_is_accepted(metric: str) -> None:
    decl = CalibObjectiveBlockDecl.model_validate(_block(metric, ["upstream"]))

    assert decl.uses_outputs == ["upstream"]


@pytest.mark.parametrize("metric", POOLABLE)
def test_an_error_over_several_outputs_stays_pooled(metric: str) -> None:
    decl = CalibObjectiveBlockDecl.model_validate(_block(metric, ["upstream", "downstream"]))

    assert decl.uses_outputs == ["upstream", "downstream"]
