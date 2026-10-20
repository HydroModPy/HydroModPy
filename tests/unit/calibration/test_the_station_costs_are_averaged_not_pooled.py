"""One efficiency per station, then the weighted mean of the costs.

A composite of one block per output (block weights) must agree with the
arithmetic written out; ``variable`` + ``objective`` is read as exactly such a
composite, at equal weights. A block over both outputs is the pooled
computation the configuration no longer lets an efficiency use; it is kept here
to show it is another number.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.optim.objective import (
    CompositeObjective,
    ConfigBlockObjective,
    SimulationOutput,
)

OBSERVED = {
    "a": np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
    "b": np.array([100.0, 200.0, 300.0, 400.0, 500.0]),
}
SIMULATED = {
    "a": np.array([5.0, 4.0, 3.0, 2.0, 1.0]),
    "b": np.array([110.0, 190.0, 310.0, 390.0, 505.0]),
}


def _nse(simulated: np.ndarray, observed: np.ndarray) -> float:
    return 1.0 - float(
        np.sum((simulated - observed) ** 2) / np.sum((observed - observed.mean()) ** 2)
    )


def _simulation() -> SimulationOutput:
    return SimulationOutput(sim_id="s", stations=("a", "b"), times=np.arange(5.0), values=SIMULATED)


def _by_hand(weights: dict[str, float]) -> float:
    costs = {name: 1.0 - _nse(SIMULATED[name], OBSERVED[name]) for name in OBSERVED}
    return sum(weights[n] * costs[n] for n in costs) / sum(weights.values())


@pytest.mark.parametrize("weights", [{"a": 1.0, "b": 1.0}, {"a": 2.0, "b": 1.0}])
def test_one_block_per_output_gives_the_same_weighted_mean(weights: dict[str, float]) -> None:
    blocks = [
        (
            ConfigBlockObjective(
                name=name,
                metric="nse",
                uses_outputs=[name],
                observed_by_output={name: OBSERVED[name]},
            ),
            weights[name],
        )
        for name in ("a", "b")
    ]

    value = CompositeObjective(blocks).evaluate(_simulation())

    assert value.total == pytest.approx(_by_hand(weights))


def test_the_pool_of_both_outputs_is_another_number() -> None:
    pooled = ConfigBlockObjective(
        name="both", metric="nse", uses_outputs=["a", "b"], observed_by_output=OBSERVED
    ).evaluate(_simulation())

    assert pooled.total != pytest.approx(_by_hand({"a": 1.0, "b": 1.0}), abs=0.1)
