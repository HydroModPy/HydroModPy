"""``pbias`` reads like ``bias``: positive when the model overestimates.

It used to follow Moriasi et al. (2007), ``100 x sum(o - s) / sum(o)``, so a
run that overestimated had a positive ``bias`` and a negative ``pbias`` (N13 of
the audit of 2026-10-20, decision m13). The sign is now ``100 x sum(s - o) /
sum(o)``, and the rule version moves from "1" to "2" because a stored score
changes sign.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.metrics import bias, pbias
from hydromodpy.results.metric_rule import METRIC_RULE_VERSION

OBSERVED = np.array([1.0, 2.0, 3.0, 4.0])


def test_pbias_is_positive_when_the_model_overestimates() -> None:
    simulated = OBSERVED * 1.1

    assert pbias(simulated, OBSERVED) == pytest.approx(10.0)
    assert bias(simulated, OBSERVED) > 0.0


def test_pbias_is_negative_when_the_model_underestimates() -> None:
    assert pbias(OBSERVED * 0.8, OBSERVED) == pytest.approx(-20.0)


def test_pbias_is_the_percent_of_the_summed_signed_error() -> None:
    simulated = np.array([2.0, 2.0, 2.0, 5.0])

    expected = 100.0 * np.sum(simulated - OBSERVED) / np.sum(OBSERVED)
    assert pbias(simulated, OBSERVED) == pytest.approx(expected)


def test_a_change_of_sign_is_a_new_rule_version() -> None:
    assert METRIC_RULE_VERSION == "2"
