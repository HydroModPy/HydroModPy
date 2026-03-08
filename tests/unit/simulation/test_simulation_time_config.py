"""Unit tests for optional simulation time-window configuration."""

from __future__ import annotations

import pytest

from hydromodpy.simulation.planning.config import SimulationConfig


def test_simulation_time_window_parses_from_mapping() -> None:
    cfg = SimulationConfig.model_validate(
        {
            "name": "time-window",
            "description": "test",
            "time": {
                "start_datetime": "2020-01-01 00:00:00",
                "end_datetime": "2020-01-02 00:00:00",
                "step_value": 6,
                "step_unit": "hour",
                "coverage_policy": "warn",
            },
            "process": [],
        }
    )

    assert cfg.time is not None
    assert cfg.time.step_value == 6
    assert cfg.time.step_unit == "hour"
    assert cfg.time.coverage_policy == "warn"


def test_simulation_time_window_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError, match="end_datetime must be greater than or equal"):
        _ = SimulationConfig.model_validate(
            {
                "name": "bad-window",
                "time": {
                    "start_datetime": "2020-01-02 00:00:00",
                    "end_datetime": "2020-01-01 00:00:00",
                },
                "process": [],
            }
        )


def test_simulation_time_window_explicit_requires_bounds() -> None:
    with pytest.raises(ValueError, match="are required when \\[simulation.time\\] is declared"):
        _ = SimulationConfig.model_validate(
            {
                "name": "explicit-without-bounds",
                "time": {
                    "step_value": 1,
                },
                "process": [],
            }
        )


def test_simulation_time_window_rejects_from_modflow_mode() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        _ = SimulationConfig.model_validate(
            {
                "name": "from-modflow",
                "time": {
                    "mode": "from_modflow",
                    "start_datetime": "2020-01-01 00:00:00",
                    "end_datetime": "2020-01-02 00:00:00",
                },
                "process": [],
            }
        )


def test_simulation_time_window_rejects_non_positive_step_value() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        _ = SimulationConfig.model_validate(
            {
                "name": "invalid-step",
                "time": {
                    "start_datetime": "2020-01-01 00:00:00",
                    "end_datetime": "2020-01-01 00:00:00",
                    "step_value": 0,
                    "step_unit": "day",
                },
                "process": [],
            }
        )
