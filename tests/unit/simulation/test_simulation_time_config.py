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
                "coverage_policy": "warn",
            },
            "process": [],
        }
    )

    assert cfg.time is not None
    assert cfg.time.coverage_policy == "warn"


def test_simulation_time_window_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError, match="end_datetime must be greater"):
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
