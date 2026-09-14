"""How wide the answer is, said in the file rather than hardcoded.

The interval reported beside a calibrated value was five per cent of the best
cost, always. That is a fine default for an efficiency score and meaningless for
a criterion solved at zero: five per cent of zero is zero, so a stream-network
calibration got no interval at all and nothing said which line would give it
one.

The block declares it. The calibrated value never moves; only what is reported
beside it does.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.calibration.runners.cli_runner import _tolerance_intervals_or_none

_SPACE = ParameterSpace.from_toml_mapping(
    {"K": {"bounds": [1.0, 5.0], "path": "flow.param.K.field.value"}}
)


def _trace(pairs: list[tuple[float, float]]) -> list[dict[str, object]]:
    return [{"parameters": {"K": value}, "objective_value": cost} for value, cost in pairs]


_SHARP = _trace([(1.0, 10.0), (2.0, 1.0), (3.0, 1.02), (4.0, 9.0), (5.0, 30.0)])
_AT_ZERO = _trace([(1.0, 40.0), (2.0, 0.0), (3.0, 12.0), (4.0, 30.0)])


class TestTheDeclaration:
    def test_the_default_is_five_per_cent_of_the_best(self) -> None:
        decl = CalibrationConfig().uncertainty

        assert decl.method == "cost_profile"
        assert decl.tolerance == 0.05
        assert decl.mode == "relative"

    def test_a_file_may_state_a_width_in_the_unit_of_the_cost(self) -> None:
        cfg = CalibrationConfig.model_validate(
            {
                "parameters": {"K": {"bounds": [1e-8, 1e-2]}},
                "uncertainty": {"mode": "absolute", "tolerance": 25.0},
            }
        )

        assert cfg.uncertainty.mode == "absolute"
        assert cfg.uncertainty.tolerance == 25.0

    def test_a_negative_width_is_refused(self) -> None:
        with pytest.raises(ValueError):
            CalibrationConfig.model_validate(
                {"parameters": {"K": {"bounds": [1e-8, 1e-2]}}, "uncertainty": {"tolerance": -1.0}}
            )

    def test_a_method_that_does_not_exist_is_refused(self) -> None:
        with pytest.raises(ValueError):
            CalibrationConfig.model_validate(
                {
                    "parameters": {"K": {"bounds": [1e-8, 1e-2]}},
                    "uncertainty": {"method": "bootstrap"},
                }
            )


class TestWhatTheRunReports:
    def test_the_declared_width_is_the_one_used(self) -> None:
        decl = CalibrationConfig.model_validate(
            {"parameters": {"K": {"bounds": [1e-8, 1e-2]}}, "uncertainty": {"tolerance": 0.001}}
        ).uncertainty

        (interval,) = _tolerance_intervals_or_none(_SHARP, ["K"], _SPACE, decl)

        assert interval.tolerance == 0.001
        assert interval.lower == interval.upper == 2.0

    def test_an_absolute_width_reaches_a_criterion_solved_at_zero(self) -> None:
        decl = CalibrationConfig.model_validate(
            {
                "parameters": {"K": {"bounds": [1e-8, 1e-2]}},
                "uncertainty": {"mode": "absolute", "tolerance": 15.0},
            }
        ).uncertainty

        (interval,) = _tolerance_intervals_or_none(_AT_ZERO, ["K"], _SPACE, decl)

        assert interval.mode == "absolute"
        assert interval.lower == 2.0
        assert interval.upper == 3.0

    def test_a_relative_width_on_a_zero_cost_reports_nothing_and_says_why(self, caplog) -> None:
        decl = CalibrationConfig().uncertainty

        with caplog.at_level("WARNING"):
            assert _tolerance_intervals_or_none(_AT_ZERO, ["K"], _SPACE, decl) == []

        assert "absolute" in caplog.text
