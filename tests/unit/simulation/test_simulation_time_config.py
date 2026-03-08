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
                "mode": "explicit",
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
    assert cfg.time.mode == "explicit"
    assert cfg.time.step_value == 6
    assert cfg.time.step_unit == "hour"
    assert cfg.time.coverage_policy == "warn"


def test_simulation_time_window_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError, match="end_datetime must be greater than or equal"):
        _ = SimulationConfig.model_validate(
            {
                "name": "bad-window",
                "time": {
                    "mode": "explicit",
                    "start_datetime": "2020-01-02 00:00:00",
                    "end_datetime": "2020-01-01 00:00:00",
                },
                "process": [],
            }
        )


def test_simulation_time_window_explicit_requires_bounds() -> None:
    with pytest.raises(ValueError, match="required when simulation.time.mode='explicit'"):
        _ = SimulationConfig.model_validate(
            {
                "name": "explicit-without-bounds",
                "time": {
                    "mode": "explicit",
                },
                "process": [],
            }
        )


def test_simulation_time_window_from_modflow_allows_omitted_bounds() -> None:
    cfg = SimulationConfig.model_validate(
        {
            "name": "from-modflow",
            "time": {
                "mode": "from_modflow",
                "coverage_policy": "warn",
            },
            "process": [],
        }
    )

    assert cfg.time is not None
    assert cfg.time.mode == "from_modflow"
    assert cfg.time.step_value == 1
    assert cfg.time.step_unit == "day"
    assert cfg.time.start_datetime is None
    assert cfg.time.end_datetime is None


def test_simulation_time_window_rejects_non_positive_step_value() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        _ = SimulationConfig.model_validate(
            {
                "name": "invalid-step",
                "time": {
                    "mode": "explicit",
                    "start_datetime": "2020-01-01 00:00:00",
                    "end_datetime": "2020-01-01 00:00:00",
                    "step_value": 0,
                    "step_unit": "day",
                },
                "process": [],
            }
        )
