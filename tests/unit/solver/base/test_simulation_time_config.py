"""Unit tests for optional simulation time-window configuration."""

from __future__ import annotations

import pytest

from hydromodpy.solver.base.planner import SimulationPlanner
from hydromodpy.solver.base.simulation_config import SimulationConfig


def test_simulation_time_window_parses_inline_step_value_unit() -> None:
    cfg = SimulationConfig.model_validate(
        {
            "name": "time-window-inline",
            "description": "test",
            "time": {
                "start_datetime": "2020-01-01 00:00:00",
                "end_datetime": "2020-01-02 00:00:00",
                "step_value": "30 day",
                "coverage_policy": "warn",
            },
            "process": [],
        }
    )

    assert cfg.time is not None
    assert cfg.time.step_value == 30
    assert cfg.time.step_unit == "day"


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


def test_simulation_time_window_rejects_conflicting_inline_and_explicit_units() -> None:
    with pytest.raises(ValueError, match="unit conflicts with simulation.time.step_unit"):
        _ = SimulationConfig.model_validate(
            {
                "name": "invalid-step-conflict",
                "time": {
                    "start_datetime": "2020-01-01 00:00:00",
                    "end_datetime": "2020-01-02 00:00:00",
                    "step_value": "30 day",
                    "step_unit": "hour",
                },
                "process": [],
            }
        )


def test_simulation_time_window_reports_sign_before_missing_unit() -> None:
    """A negative step_value with no unit gets the sign diagnosis, not 'has no unit'."""
    with pytest.raises(ValueError, match="must be a positive integer"):
        _ = SimulationConfig.model_validate(
            {
                "name": "negative-step-no-unit",
                "time": {
                    "start_datetime": "2020-01-01 00:00:00",
                    "end_datetime": "2020-01-02 00:00:00",
                    "step_value": -5,
                },
                "process": [],
            }
        )


def test_simulation_time_window_rejects_bare_step_value_without_unit() -> None:
    with pytest.raises(ValueError, match="simulation.time.step_value has no unit"):
        _ = SimulationConfig.model_validate(
            {
                "name": "bare-step-value",
                "time": {
                    "start_datetime": "2020-01-01 00:00:00",
                    "end_datetime": "2020-01-02 00:00:00",
                    "step_value": 1,
                },
                "process": [],
            }
        )


def test_simulation_transient_helper_builds_flow_transport_processes() -> None:
    cfg = SimulationConfig.transient(
        time=("2020-01-01", "2020-01-02", "1 day"),
        flow="modflow_nwt",
        transport="mt3dms",
    )

    assert [process.id for process in cfg.process] == ["flow_main", "transport_main"]
    assert [process.kind for process in cfg.process] == ["flow", "transport"]
    assert cfg.process[1].solvers == ["mt3dms"]


def test_simulation_mesh_process_uses_backend_not_solvers() -> None:
    cfg = SimulationConfig.model_validate(
        {
            "name": "mesh-only",
            "process": [
                {
                    "id": "mesh_main",
                    "kind": "mesh",
                    "backend": "catchment",
                }
            ],
        }
    )

    process = cfg.process[0]
    assert process.kind == "mesh"
    assert process.backend == "catchment"
    assert process.solvers == []

    plan = SimulationPlanner().build(cfg)
    assert len(plan.runs) == 1
    assert plan.runs[0].id == "mesh_main::catchment"
    assert plan.runs[0].process_type == "mesh"
    assert plan.runs[0].backend == "catchment"
    assert plan.runs[0].is_solver_backed is False


def _time(**extra: object) -> dict[str, object]:
    return {
        "start_datetime": "2020-01-01",
        "end_datetime": "2020-12-31",
        "step_value": "1 month",
        **extra,
    }


@pytest.mark.parametrize(
    ("extra", "window_length", "window"),
    [
        ({"window_length": "6 months"}, "6 months", "all"),
        ({"window_length": "1 year", "window": 2}, "1 year", 2),
        ({"window_length": "30 days", "window": "all"}, "30 days", "all"),
        ({"window": 1}, None, 1),
    ],
    ids=["length", "one window", "all", "one window of one"],
)
def test_the_windows_are_read_from_the_time_section(
    extra: dict[str, object], window_length: str | None, window: object
) -> None:
    cfg = SimulationConfig.model_validate({"name": "w", "time": _time(**extra), "process": []})

    assert (cfg.time.window_length, cfg.time.window) == (window_length, window)


@pytest.mark.parametrize(
    ("extra", "match"),
    [
        ({"window_length": "6"}, "window_length is a calendar length"),
        ({"window_length": "2 weeks"}, "positive whole number"),
        ({"window_length": "6 months", "window": 0}, "window is 'all' or a window number"),
        ({"window_length": "6 months", "window": True}, "window is 'all' or a window number"),
        ({"window_length": "6 months", "window": "last"}, "window is 'all' or a window number"),
        ({"window": 2}, "window_length, which is not set"),
    ],
    ids=["bare number", "weeks", "zero", "boolean", "word", "window without length"],
)
def test_a_bad_window_is_refused_with_its_key(extra: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        SimulationConfig.model_validate({"name": "w", "time": _time(**extra), "process": []})
