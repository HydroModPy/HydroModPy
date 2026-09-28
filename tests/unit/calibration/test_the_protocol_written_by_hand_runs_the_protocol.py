"""Example 04 writes its protocol out as phases, and the two must run the same.

``run_calibration_by_hand.toml`` drops the protocol name and declares
the stages it writes. If the protocol changes what it writes, or the file
drifts, the two stop being the same calibration and this test says where.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.calibration.runners import staged_runner
from hydromodpy.config import HydroModPyConfig

pytestmark = pytest.mark.fast

EXAMPLE_04 = Path(__file__).resolve().parents[3] / (
    "examples/projects/04_streamflow_intermittence_in_transient"
)


@pytest.fixture(scope="module")
def calibrations():
    protocol = HydroModPyConfig.from_toml(EXAMPLE_04 / "run_calibration.toml").calibration
    by_hand = HydroModPyConfig.from_toml(EXAMPLE_04 / "run_calibration_by_hand.toml").calibration
    return protocol, by_hand


def test_only_the_protocol_name_differs(calibrations) -> None:
    protocol, by_hand = calibrations

    assert protocol.protocol is not None
    assert by_hand.protocol is None
    first = protocol.model_dump(mode="json", exclude={"protocol"})
    second = by_hand.model_dump(mode="json", exclude={"protocol"})
    assert first == second


def test_each_stage_runs_the_same_search(calibrations) -> None:
    protocol, by_hand = calibrations

    for ours, theirs in zip(protocol.phases, by_hand.phases, strict=True):
        assert staged_runner._phase_config(protocol, ours).model_dump(
            mode="json"
        ) == staged_runner._phase_config(by_hand, theirs).model_dump(mode="json")
