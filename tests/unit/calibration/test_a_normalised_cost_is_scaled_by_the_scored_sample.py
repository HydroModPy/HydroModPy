"""``normalize_cost`` divides by the spread of what the block scores.

The scale was the standard deviation of the observed values as given to the
block, before the burn-in. The metric reads the values after it, so a burn-in
that cut a high-variance spin-up left the cost divided by a spread the scored
sample does not have.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from hydromodpy.calibration.optim import objective as objective_module
from hydromodpy.calibration.optim.objective import ConfigBlockObjective

# Six wild spin-up values, then six calm ones.
_OBSERVED = np.array([10.0, 0.5, 9.0, 1.0, 8.0, 2.0, 5.0, 5.2, 4.9, 5.1, 5.0, 5.3])


def _block(observed: np.ndarray, **kwargs) -> ConfigBlockObjective:
    return ConfigBlockObjective(
        name="q",
        metric="rmse",
        uses_outputs=["q"],
        observed_by_output={"q": observed},
        normalize_cost=True,
        **kwargs,
    )


def test_the_scale_is_the_spread_of_the_values_left_after_the_burn_in() -> None:
    block = _block(_OBSERVED, warmup=6)

    value = block.evaluate({"q": _OBSERVED + 0.3})

    scored = _OBSERVED[6:]
    assert value.components["q.reference_scale"] == pytest.approx(float(np.std(scored)))
    assert value.components["q.normalized_cost"] == pytest.approx(
        value.components["q.raw_cost"] / float(np.std(scored))
    )


def test_the_scale_is_unchanged_without_a_burn_in() -> None:
    block = _block(_OBSERVED)

    value = block.evaluate({"q": _OBSERVED + 0.3})

    assert value.components["q.reference_scale"] == pytest.approx(float(np.std(_OBSERVED)))


def test_the_fallback_of_a_flat_sample_is_logged_once(caplog) -> None:
    flat = np.full(8, 4.0)
    block = _block(flat)

    with caplog.at_level(logging.WARNING, logger=objective_module.__name__):
        first = block.evaluate({"q": flat + 1.0})
        block.evaluate({"q": flat + 2.0})

    assert first.components["q.reference_scale"] == pytest.approx(4.0)
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 1
    assert "mean absolute" in messages[0]
